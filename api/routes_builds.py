"""Build routes: start/cancel builds, rebuild/regen/animate/retheme, SSE events and
status, list generation, theme preview and style samples.
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from api import state
from api.cards import _free_all_vram, _resolve_card_source, _resolve_partners
from api.jobs_build import _run_build, _run_card_build
from api.jobs_rebuild import _run_rebuild
from api.jobs_regen import _run_animate_cards, _run_regen_cards
from api.jobs_retheme import _run_retheme
from api.models import (
    AnimateCardsRequest,
    BuildRequest,
    CardBuildRequest,
    GenSettingsModel,
    RebuildRequest,
    RegenCardsRequest,
    RethemeRequest,
    _resolve_gen_settings,
)
from api.state import (
    _RATE_LIMIT_BUILD_REQUESTS,
    _RATE_LIMIT_WINDOW,
    _art_lock,
    _check_rate_limit,
    _jobs,
    _load_deck_from_disk,
    _progress,
    _require_job_id,
    _scryfall,
    _sse_stream,
)
from collection import load_owned_names, owned_count
from commander_analysis import build_commander_profile
from deck_builder import (
    SOURCE_SCRYFALL,
    DeckBuilder,
    aggregate_duplicates,
    compute_stats,
)
from image_gen import ImageGen
from playstyle import PLAYSTYLES, get_slot_adjustments, resolve_themes
from services import (
    _comfyui_vram_free_gb,
    _ensure_comfyui_ready,
    _wait_for_comfyui_unload,
    _wait_for_ollama_evict,
)
from themer import Themer

router = APIRouter()


@router.get("/api/deck/active")
async def get_active_job():
    """Return the most-recent in-memory building job so a refresh can reconnect.
    Does NOT fall back to disk — that auto-loaded random old decks on first visit."""
    building = [(jid, j) for jid, j in _jobs.items() if j.get("status") == "building"]
    if building:
        jid, _ = building[-1]
        return {"job_id": jid, "status": "building"}
    return {"job_id": None, "status": "none"}


class GenerateListRequest(BaseModel):
    commander_name: str = Field("", max_length=120)
    partner_names:  list[str] = Field(default_factory=list, max_length=2)
    playstyle:      str = "auto"
    bracket:        int = 3
    use_collection: bool = False   # prefer owned cards (Myth Suite C4)
    card_source:    str = Field("", max_length=24)   # see _resolve_card_source


@router.post("/api/deck/generate-list")
def generate_list(req: GenerateListRequest):
    """Phase 1 of the two-phase flow: build the 99-card decklist (NO theming/art)
    so the theme step can show the deck's real creature types for per-tribe reskin.
    Returns the commander, the (duplicate-aggregated) deck, stats, and the
    frequency-ordered creature subtypes present. Runs in FastAPI's threadpool."""
    name = (req.commander_name or "").strip()
    if not name:
        raise HTTPException(400, "commander_name is required")
    card = _scryfall.get_card_by_name(name, fuzzy=True)
    if not card:
        raise HTTPException(404, f"Commander not found: {name}")
    ps_label       = PLAYSTYLES.get(req.playstyle, PLAYSTYLES["auto"])["label"]
    partners       = _resolve_partners(card, req.partner_names)
    profile        = build_commander_profile(card, partners)
    active_themes  = resolve_themes(req.playstyle, profile.themes)
    slot_overrides = get_slot_adjustments(req.playstyle)
    source = _resolve_card_source(req.card_source, req.use_collection)
    owned = load_owned_names() if source != SOURCE_SCRYFALL else set()
    builder = DeckBuilder(_scryfall)
    deck = builder.build(
        profile, theme_override=active_themes, slot_overrides=slot_overrides,
        playstyle_label=ps_label, bracket=req.bracket, owned=owned,
        card_source=source, partner_count=len(partners))
    # Partner/companion commanders aren't the face — render them as cards, same as the
    # import branch. This deck round-trips to phase 2 as `prebuilt_deck`, so appending
    # here (once) is what carries the partner through to the actual themed/rendered
    # build — phase 2 must NOT append it again.
    for p in partners:
        pc = dict(p); pc.setdefault("quantity", 1); deck.append(pc)
    deck  = aggregate_duplicates(deck)
    stats = compute_stats(card, deck, partners=partners)
    collection_stats = None
    if source != SOURCE_SCRYFALL:
        _spells = [card] + [c for c in deck
                            if "basic" not in (c.get("type_line", "") or "").lower()]
        collection_stats = {
            "source": source, "shortfall": builder.shortfall,
            "enabled": True, "owned": owned_count(_spells, owned),
            "total": len(_spells), "collection_size": len(owned),
        }

    # Frequency-ordered creature subtypes (commander + deck) for the reskin UI.
    from collections import Counter
    # Card-TYPE words that can ride along on multi-type / DFC / adventure type
    # lines but are NOT creature subtypes (so they shouldn't be reskin fields).
    _NON_TRIBE_WORDS = {"Saga", "Creature", "Enchantment", "Artifact", "Land",
                        "Sorcery", "Instant", "Planeswalker", "Battle", "Adventure",
                        "Legendary", "Snow", "Token", "Basic", "Tribal"}
    counts: "Counter[str]" = Counter()
    for c in [card] + deck:
        tl = c.get("type_line", "") or ""
        if "creature" not in tl.lower():
            continue
        norm = tl.replace(" - ", " — ")
        if "—" not in norm:
            continue
        for s in norm.split("—", 1)[1].strip().split():
            # Only count real creature subtypes. Skip split/MDFC noise ("//") and
            # card-TYPE words that ride along on multi-type / DFC / adventure type
            # lines (Saga, Enchantment, Creature, Sorcery, Adventure, …) — those
            # aren't tribes and shouldn't appear as reskin fields.
            if s and s.isalpha() and s not in _NON_TRIBE_WORDS:
                counts[s] += 1
    tribes = [{"type": t, "count": n} for t, n in counts.most_common()]

    return {"commander": card, "deck": deck, "stats": stats, "tribes": tribes,
            "playstyle": ps_label, "bracket": req.bracket, "collection": collection_stats}


class ThemePreviewRequest(BaseModel):
    """Cheap pre-build preview of the creative direction (no art generation)."""
    commander_name:   str = Field("", max_length=120)
    theme_spec:       Optional[dict] = None
    art_style:        str = "mtg_fantasy"
    creativity:       str = "balanced"
    commander_prompt: str = Field("", max_length=500)
    llm_model:        Optional[str] = None


# Network-free representative cards so the preview shows how a land, a creature,
# and a removal spell each get themed (alongside the real commander).
_PREVIEW_SAMPLE_CARDS = [
    {"name": "Forest", "type_line": "Basic Land — Forest", "oracle_text": "({T}: Add {G}.)",
     "cmc": 0, "colors": [], "color_identity": []},
    {"name": "Grizzly Bears", "type_line": "Creature — Bear", "oracle_text": "",
     "cmc": 2, "colors": ["G"], "color_identity": ["G"], "power": "2", "toughness": "2"},
    {"name": "Murder", "type_line": "Instant", "oracle_text": "Destroy target creature.",
     "cmc": 3, "colors": ["B"], "color_identity": ["B"]},
]


@router.post("/api/deck/theme-preview")
def theme_preview(req: ThemePreviewRequest):
    """Cheap 'Preview creative direction' step (no art gen): build the world bible
    from the structured inputs + theme a 3-card sample, so the user can iterate on
    their idea before committing to a full ~30-min build. Returns the world bible,
    sample themed cards, and which must-include motifs are covered."""
    spec = req.theme_spec or {}
    if not any((spec.get(k) for k in ("setting", "genres", "moods", "lighting", "inspiration"))):
        raise HTTPException(400, "Describe your world first (at least a Setting) to preview.")

    # Resolve the real commander when given (so its themed name is shown); fall back
    # to a generic protagonist label otherwise.
    cmd_name = (req.commander_name or "").strip()
    cmd_card = _scryfall.get_card_by_name(cmd_name, fuzzy=True) if cmd_name else None
    cmd_for_theme = (cmd_card or {"name": cmd_name or "The Commander",
                                  "type_line": "Legendary Creature", "oracle_text": "",
                                  "cmc": 0, "colors": [], "color_identity": []})

    from image_gen import get_all_presets as _gap
    from themer import LLM_CATALOG as _CATALOG
    from themer import OLLAMA_MODEL as _DEF_MODEL
    from themer import (
        _deck_color_identity,
        build_color_factions,
        build_creative_brief,
        verify_motif_coverage,
    )
    from themer import _generate_style_guide as _gen_style_guide
    _all_p = _gap()
    _style = _all_p.get(req.art_style or "mtg_fantasy",
                        _all_p.get("mtg_fantasy", next(iter(_all_p.values()))))

    # ── VRAM headroom for the LLM ─────────────────────────────────────────────
    # If FLUX is resident from a previous render, llama-swap can fail to load the
    # preview model (verified: qwen3:32b → upstream exit at 3.5 GB free). Mirror
    # the build path's dance: when free VRAM < model size + margin, ask ComfyUI to
    # unload its models first. No-ops when there's already room.
    _mkey = req.llm_model or _DEF_MODEL
    _msize = next((m.get("size_gb", 10.0) for m in _CATALOG if m.get("key") == _mkey), 10.0)
    _free = _comfyui_vram_free_gb()
    if _free is not None and _free < _msize + 2.0:
        print(f"  [theme-preview] {_free:.1f} GB free < {_msize:.0f}+2 GB needed for {_mkey} — "
              f"unloading ComfyUI models first")
        _wait_for_comfyui_unload()

    try:
        T = Themer(model=_mkey)
        bible = build_creative_brief(
            spec, cmd_for_theme.get("name", ""), req.commander_prompt or "",
            style_guide_hint=_style.get("style_guide_hint", ""),
            creativity=req.creativity or "balanced", model=T.model)
        style_guide = _gen_style_guide(
            bible["world"], cmd_for_theme.get("name", ""),
            commander_prompt=req.commander_prompt or "",
            style_guide_hint=_style.get("style_guide_hint", ""),
            must_include=bible["must_include"], model=T.model)

        # Set Bible: per-colour factions for the commander's colour identity (the
        # whole EDH deck shares it). Generated before sampling so the preview cards
        # already reflect their factions, and returned so the UI can show the world.
        _pcolors = (cmd_for_theme.get("color_identity")
                    or _deck_color_identity(cmd_for_theme, _PREVIEW_SAMPLE_CARDS)
                    or ["W", "U", "B", "R", "G"])
        _fac = build_color_factions(bible["world"], bible.get("palette", ""), _pcolors,
                                    creativity=req.creativity or "balanced", model=T.model)
        bible["colors"]          = [c for c in ["W", "U", "B", "R", "G"] if c in _fac.get("factions", {})]
        bible["color_factions"]  = _fac.get("factions", {})
        bible["mechanic_flavor"] = _fac.get("mechanic_flavor", {})
        bible["lore"]            = _fac.get("lore", "")

        sample_cards = [cmd_for_theme] + _PREVIEW_SAMPLE_CARDS
        entries = T._theme_batch(
            bible["world"], cmd_for_theme.get("name", ""), sample_cards, 0, style_guide,
            commander_prompt=req.commander_prompt or "", batch_commander_idx=0,
            world_zones=bible["zones"],
            themer_medium=_style.get("themer_medium", ""),
            themer_quality=_style.get("themer_quality", ""),
            world_bible=bible)
        by_idx = {e.get("idx"): e for e in entries}
        samples = []
        for i, c in enumerate(sample_cards):
            e = by_idx.get(i, {})
            samples.append({
                "original":    c["name"],
                "type_line":   c["type_line"],
                "themed_name": e.get("themed_name", ""),
                "art_prompt":  e.get("art_prompt", ""),
            })
        # Cards-only (the style guide never reaches FLUX); on a 3-card sample some
        # motifs will read ⚠ — that's expected and disclaimed in the UI panel.
        coverage = verify_motif_coverage(
            bible["must_include"], [s["art_prompt"] for s in samples])
    except Exception as e:
        print(f"  [theme-preview] error: {e}")
        traceback.print_exc()
        raise HTTPException(503, "Preview failed (is the LLM gateway up?).")

    return {
        "world_bible": {k: bible.get(k) for k in
                        ("world", "must_include", "signature_details", "palette", "zones",
                         "creativity", "colors", "color_factions", "mechanic_flavor", "lore")},
        "style_guide": style_guide,
        "samples":     samples,
        "coverage":    coverage,
        "commander":   (cmd_card or {}).get("name", cmd_name),
    }


# ── Visual taste test (style sample) ──────────────────────────────────────────
# Renders the text-preview's sample art_prompts as REAL FLUX/SDXL art (≤4 images,
# ~30s each) so the user can judge the deck's actual look before a ~40-min full
# build. Deliberately re-renders the EXACT prompts the user just read in the
# ThemePreview panel — what you previewed is what renders. No theming, no faces;
# the only GPU tenant is the image model (LLM is evicted first, same as builds).

class StyleSampleEntry(BaseModel):
    themed_name: str = Field("", max_length=120)
    art_prompt:  str = Field("", max_length=900)
    type_line:   str = Field("", max_length=80)


class StyleSampleRequest(BaseModel):
    samples:      List[StyleSampleEntry]
    art_style:    str = "mtg_fantasy"
    model_speed:  str = "quality"
    checkpoint:   Optional[str] = None
    llm_model:    Optional[str] = None   # which LLM to evict (it just ran the text preview)
    gen_settings: Optional[GenSettingsModel] = None


_STYLE_SAMPLE_DIR = state.RENDER_DIR / "style_samples"


def _run_style_sample(job_id: str, req: StyleSampleRequest):
    job = _jobs[job_id]
    out_dir = _STYLE_SAMPLE_DIR / job_id
    try:
        if not _ensure_comfyui_ready(wait_timeout=240.0):
            job.update(status="error", error="ComfyUI is not running and could not be started.")
            return
        from themer import OLLAMA_MODEL as _DEF
        _wait_for_ollama_evict(req.llm_model or _DEF)

        with _art_lock:   # never contend with a real build for the GPU
            gen = ImageGen(model_speed=req.model_speed, art_style=req.art_style,
                           checkpoint=req.checkpoint,
                           gen_settings=_resolve_gen_settings(req.gen_settings))
            if not gen.available:
                job.update(status="error", error="No usable checkpoint found in ComfyUI.")
                return
            # Match deck builds: scale dark-only LoRAs to the sample's mood so the
            # taste test renders with the same stack a real build would use.
            gen.theme_darkness = _theme_darkness_score_safe(
                " ".join(s.art_prompt for s in req.samples))

            out_dir.mkdir(parents=True, exist_ok=True)
            for i, s in enumerate(req.samples[:4]):
                if job.get("cancel_event") and job["cancel_event"].is_set():
                    break
                job["current"] = s.themed_name
                path = gen.generate(s.art_prompt, str(out_dir / f"sample_{i}"),
                                    card_type=s.type_line or "",
                                    cancel_event=job.get("cancel_event"))
                job["images"].append({
                    "idx": i, "themed_name": s.themed_name,
                    "ok": path is not None,
                    "url": f"/api/deck/style-sample/{job_id}/img/{i}" if path else None,
                })
        job["status"] = "done"
    except Exception as e:
        traceback.print_exc()
        job.update(status="error", error=str(e))
    finally:
        job["current"] = None


def _theme_darkness_score_safe(hint: str) -> float:
    try:
        from image_gen import _theme_darkness_score
        return _theme_darkness_score(hint)
    except Exception:
        return 1.0


@router.post("/api/deck/style-sample")
async def start_style_sample(req: StyleSampleRequest, background_tasks: BackgroundTasks, request: Request):
    prompts = [s for s in req.samples if (s.art_prompt or "").strip()]
    if not prompts:
        raise HTTPException(400, "No sample prompts to render — run the creative-direction preview first.")
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip, _RATE_LIMIT_BUILD_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_BUILD_REQUESTS} per {_RATE_LIMIT_WINDOW}s")
    # One GPU: refuse while a build/sample is actively running.
    for jid, j in _jobs.items():
        if j.get("status") in ("queued", "building"):
            raise HTTPException(409, "Another build is running — wait for it to finish (one GPU).")
    job_id = uuid.uuid4().hex[:16]
    _jobs[job_id] = {"status": "building", "kind": "style_sample", "images": [],
                     "current": None, "total": min(len(prompts), 4),
                     "cancel_event": threading.Event(), "created_at": time.time()}
    req.samples = prompts
    background_tasks.add_task(_run_style_sample, job_id, req)
    return {"job_id": job_id}


@router.get("/api/deck/style-sample/{job_id}")
async def style_sample_status(job_id: str):
    j = _jobs.get(job_id)
    if not j or j.get("kind") != "style_sample":
        raise HTTPException(404, "Sample job not found")
    return {"status": j.get("status"), "error": j.get("error"),
            "current": j.get("current"), "total": j.get("total"),
            "images": j.get("images", [])}


@router.get("/api/deck/style-sample/{job_id}/img/{idx}")
async def style_sample_image(job_id: str, idx: int):
    _require_job_id(job_id)
    path = _STYLE_SAMPLE_DIR / job_id / f"sample_{idx}.png"
    if not path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(path, media_type="image/png")


@router.post("/api/deck/build")
async def build_deck(req: BuildRequest, background_tasks: BackgroundTasks, request: Request):
    # Must either generate from a commander or import an existing decklist.
    if not (req.commander_name.strip() or req.deck_url.strip() or req.deck_list.strip()):
        raise HTTPException(400, "Provide a commander name, or a deck URL / decklist to import.")

    # Rate limiting: prevent request floods from exhausting GPU/VRAM
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip, _RATE_LIMIT_BUILD_REQUESTS):
        raise HTTPException(
            429,
            f"Rate limited — max {_RATE_LIMIT_BUILD_REQUESTS} builds per {_RATE_LIMIT_WINDOW}s"
        )

    job_id = uuid.uuid4().hex[:16]
    _jobs[job_id]     = {"status": "queued", "cancel_event": threading.Event(), "created_at": time.time()}
    _progress[job_id] = []
    background_tasks.add_task(_run_build, job_id, req)
    return {"job_id": job_id}


@router.post("/api/card/build")
async def build_single_card(req: CardBuildRequest, background_tasks: BackgroundTasks, request: Request):
    """Build a single user-authored custom card (theme + optional art + render)."""
    if not (req.card.name or "").strip():
        raise HTTPException(400, "Give the card a name.")

    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip, _RATE_LIMIT_BUILD_REQUESTS):
        raise HTTPException(
            429, f"Rate limited — max {_RATE_LIMIT_BUILD_REQUESTS} builds per {_RATE_LIMIT_WINDOW}s")

    job_id = uuid.uuid4().hex[:16]
    _jobs[job_id]     = {"status": "queued", "cancel_event": threading.Event(), "created_at": time.time()}
    _progress[job_id] = []
    background_tasks.add_task(_run_card_build, job_id, req)
    return {"job_id": job_id}


@router.post("/api/deck/{job_id}/cancel")
async def cancel_deck_build(job_id: str, background_tasks: BackgroundTasks):
    """
    Signal a running build to stop after the current card finishes.

    Also immediately schedules VRAM eviction in a background task so that
    ComfyUI and Ollama begin releasing GPU memory right away — without waiting
    for the build thread to finish its current card and render step.  This
    prevents the system-memory / disk-thrash spike that happens when 20+ GB of
    GPU memory is released all at once while the render loop is still running.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    ev = job.get("cancel_event")
    if ev and not ev.is_set():
        ev.set()
        # Only one eviction in flight per job — guard with a flag so we don't
        # race the build worker's own cleanup.
        if not job.get("vram_freeing"):
            job["vram_freeing"] = True
            background_tasks.add_task(_free_all_vram, job_id)
        return {"status": "cancelling"}
    return {"status": "already done or not cancellable"}


@router.post("/api/deck/{job_id}/rebuild")
async def rebuild_deck(job_id: str, req: RebuildRequest, background_tasks: BackgroundTasks, request: Request):
    """
    Start a new build job that skips theming and re-uses the art prompts
    already saved in deck.json.  Returns a new job_id so the original build
    is preserved and the client can watch progress on the new one.
    """
    _require_job_id(job_id)
    # Rate limiting: prevent request floods
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip, _RATE_LIMIT_BUILD_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_BUILD_REQUESTS} builds per {_RATE_LIMIT_WINDOW}s")

    # Verify the source deck actually exists (either in memory or on disk)
    source_ok = (
        (job_id in _jobs and _jobs[job_id].get("status") in ("done", "rendering"))
        or (state.RENDER_DIR / job_id / "deck.json").exists()
    )
    if not source_ok:
        raise HTTPException(404, f"Source deck not found: {job_id}")

    new_job_id = uuid.uuid4().hex[:16]
    _jobs[new_job_id]     = {"status": "queued", "cancel_event": threading.Event(), "created_at": time.time()}
    _progress[new_job_id] = []
    background_tasks.add_task(_run_rebuild, new_job_id, job_id, req)
    return {"job_id": new_job_id}


@router.post("/api/deck/{job_id}/regen-cards")
async def regen_cards(job_id: str, req: RegenCardsRequest, background_tasks: BackgroundTasks, request: Request):
    """
    Regenerate art for a specific subset of cards in an existing deck.

    Writes results back into the source deck's render directory so the deck
    view can refresh individual card tiles without navigating away.
    Returns a new job_id for SSE progress — the client should listen to
    ``/api/deck/{new_job_id}/events`` for ``card_ready`` and ``done`` events.
    """
    _require_job_id(job_id)
    # Rate limiting: prevent request floods
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip, _RATE_LIMIT_BUILD_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_BUILD_REQUESTS} builds per {_RATE_LIMIT_WINDOW}s")

    if not req.cards:
        raise HTTPException(400, "No cards specified")
    source_ok = (
        (job_id in _jobs and _jobs[job_id].get("status") in ("done", "rendering"))
        or (state.RENDER_DIR / job_id / "deck.json").exists()
    )
    if not source_ok:
        raise HTTPException(404, f"Source deck not found: {job_id}")

    new_job_id = uuid.uuid4().hex[:16]
    _jobs[new_job_id]     = {"status": "queued", "cancel_event": threading.Event(), "created_at": time.time()}
    _progress[new_job_id] = []
    background_tasks.add_task(_run_regen_cards, new_job_id, job_id, req)
    return {"job_id": new_job_id}


@router.get("/api/video-health")
def video_health():
    """Whether an image-to-video model is installed + ready (gates the UI)."""
    import card_video
    return card_video.health_check()


@router.get("/api/video-presets")
def video_presets():
    """Motion presets, foil styles and output formats for the Animate panel."""
    import card_video
    return {"presets": card_video.motion_presets(),
            "foil_styles": card_video.foil_styles(),
            "formats": card_video.format_options(),
            "loop_styles": card_video.loop_styles(),
            "caps": card_video.video_caps()}


@router.post("/api/deck/{job_id}/animate-cards")
async def animate_cards(job_id: str, req: AnimateCardsRequest,
                        background_tasks: BackgroundTasks, request: Request):
    """
    Animate a subset of cards (image-to-video on the art, recomposite, encode MP4).
    Returns a new job_id; listen on ``/api/deck/{new_job_id}/events`` for
    ``video_ready`` and ``done`` events. MP4s land in the SOURCE deck's videos/.
    """
    _require_job_id(job_id)
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip, _RATE_LIMIT_BUILD_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_BUILD_REQUESTS} per {_RATE_LIMIT_WINDOW}s")
    if not req.cards:
        raise HTTPException(400, "No cards specified")
    source_ok = (
        (job_id in _jobs and _jobs[job_id].get("status") in ("done", "rendering"))
        or (state.RENDER_DIR / job_id / "deck.json").exists()
    )
    if not source_ok:
        raise HTTPException(404, f"Source deck not found: {job_id}")

    new_job_id = uuid.uuid4().hex[:16]
    _jobs[new_job_id]     = {"status": "queued", "cancel_event": threading.Event(), "created_at": time.time()}
    _progress[new_job_id] = []
    background_tasks.add_task(_run_animate_cards, new_job_id, job_id, req)
    return {"job_id": new_job_id}


@router.post("/api/deck/{job_id}/retheme")
async def retheme_deck(job_id: str, req: RethemeRequest, background_tasks: BackgroundTasks):
    """
    Re-run Ollama theming for an existing deck without regenerating art.

    Returns a new job_id.  The client can watch progress on
    ``/api/deck/{new_job_id}/events`` and navigate to the new deck when done.
    """
    _require_job_id(job_id)
    source_ok = (
        (job_id in _jobs and _jobs[job_id].get("status") in ("done", "rendering"))
        or (state.RENDER_DIR / job_id / "deck.json").exists()
    )
    if not source_ok:
        raise HTTPException(404, f"Source deck not found: {job_id}")

    new_job_id = uuid.uuid4().hex[:16]
    _jobs[new_job_id]     = {"status": "queued", "cancel_event": threading.Event(), "created_at": time.time()}
    _progress[new_job_id] = []
    background_tasks.add_task(_run_retheme, new_job_id, job_id, req)
    return {"job_id": new_job_id}


@router.get("/api/deck/{job_id}/events")
async def deck_events(job_id: str, request: Request):
    _require_job_id(job_id)
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")
    return StreamingResponse(
        _sse_stream(job_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/deck/{job_id}/status")
async def deck_status(job_id: str):
    _require_job_id(job_id)
    job = _jobs.get(job_id)
    if not job:
        # Fall back to disk — server may have reloaded after the build finished
        disk = _load_deck_from_disk(job_id)
        if disk:
            _jobs[job_id] = disk   # re-hydrate in-memory cache
            return {"status": "done", "error": None}
        raise HTTPException(404, "Job not found")
    return {"status": job["status"], "error": job.get("error")}
