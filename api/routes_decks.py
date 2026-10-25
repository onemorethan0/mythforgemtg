"""Deck routes: read, list, import, duplicate/delete, images, export, 3D.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
import uuid
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import (
    Response,
    FileResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel, Field

import commander_analysis
import deck_import
from api import state
from api.cards import _download_art_to, _imported_card_to_stored, _is_single_card
from api.collection_data import _annotate_owned
from api.models import SearchRequest
from api.routes_strength import _engine_fingerprint, _gauntlet_analyze
from api.state import (
    _3d_jobs,
    _3d_progress,
    _jobs,
    _load_deck_from_disk,
    _progress,
    _require_job_id,
    _scryfall,
    _serializable_job,
)
from deck_builder import compute_stats
from exporter import build_pdf, build_video_zip, build_zip
from model3d import Model3DGen, generate_commander_3d
from playstyle import PLAYSTYLE_ORDER, PLAYSTYLES

logger = logging.getLogger("server")
router = APIRouter()


# ── Routes ─────────────────────────────────────────────────────────────────────

class ImportPreviewRequest(BaseModel):
    source:        str  = Field("", max_length=20000)  # URL or pasted decklist text
    force_refresh: bool = False                          # bypass the on-disk cache


@router.post("/api/deck/import-preview")
def import_preview(req: ImportPreviewRequest):
    """Fetch + resolve a deck URL / pasted list WITHOUT building, so the UI can
    confirm the commander and card count first. Cached, so re-previewing is free."""
    if not req.source.strip():
        raise HTTPException(400, "Provide a deck URL or paste a decklist.")
    try:
        imp = deck_import.import_deck(req.source, _scryfall, force_refresh=req.force_refresh)
    except deck_import.DeckImportError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("deck import failed", exc_info=e)
        raise HTTPException(500, "Import failed.")

    colors = sorted({c for card in ([imp.commander] if imp.commander else []) + imp.deck
                     for c in (card.get("color_identity") or [])})
    cmd = imp.commander
    return {
        "source":       imp.source,
        "name":         imp.name,
        "commander":    None if not cmd else {
            "name":      cmd.get("name"),
            "type_line": cmd.get("type_line", "").split(" // ")[0],
            "image_url": (cmd.get("image_uris") or {}).get("normal", ""),
        },
        "partners":     [p.get("name") for p in imp.partners],
        "auto_face":    imp.auto_face,
        # Unique maindeck cards (name + type) so the UI can offer per-card face
        # assignment for non-Commander imports without re-fetching the deck.
        "cards":        [{"name": c.get("name", ""),
                          "type_line": (c.get("type_line", "") or "").split(" // ")[0]}
                         for c in imp.deck],
        "unique_cards": len(imp.deck),
        "total_cards":  imp.total_cards(),
        "colors":       colors,
        "unresolved":   imp.unresolved,
        "simulation":   _gauntlet_analyze(imp.commander, imp.deck, partners=imp.partners),
    }


class ImportSaveRequest(BaseModel):
    source:            str  = Field("", max_length=20000)  # URL or pasted decklist text
    force_refresh:     bool = False
    is_commander_deck: bool = True
    commander_name:    str  = Field("", max_length=120)    # optional face override


@router.post("/api/deck/import-save")
def import_save(req: ImportSaveRequest):
    """Store an imported decklist in the library WITHOUT generating art, so it can be
    recalled from History like a generated deck (shown with its ORIGINAL Scryfall art) and
    rethemed later. Non-destructive: writes a fresh deck.json under a new job id; re-saving
    the same deck creates a new entry (the user chose an explicit Save button, not dedup)."""
    if not req.source.strip():
        raise HTTPException(400, "Provide a deck URL or paste a decklist.")
    try:
        imp = deck_import.import_deck(req.source, _scryfall, force_refresh=req.force_refresh)
    except deck_import.DeckImportError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("deck import failed", exc_info=e)
        raise HTTPException(500, "Import failed.")

    card = imp.commander
    override = (req.commander_name or "").strip()
    if override and (card is None or override.lower() not in (card.get("name", "") or "").lower()):
        ov = _scryfall.get_card_by_name(override, fuzzy=True)
        if ov:
            card = ov
    if not card:
        raise HTTPException(400, "Couldn't read any cards from that deck.")

    deck = list(imp.deck)
    for p in imp.partners:                      # partners/companions render as cards
        pc = dict(p); pc.setdefault("quantity", 1); deck.append(pc)
    stats = compute_stats(card, deck, partners=imp.partners)
    face_auto = bool(imp.auto_face) and card is imp.commander

    job_id = uuid.uuid4().hex[:16]
    (state.RENDER_DIR / job_id).mkdir(parents=True, exist_ok=True)
    deck_slug = ("".join(ch if ch.isalnum() else "_" for ch in card.get("name", ""))[:28]
                 + "_" + job_id[:8])
    payload = {
        "status":            "done",
        "commander":         _imported_card_to_stored(card, 0),
        "deck":              [_imported_card_to_stored(c, i) for i, c in enumerate(deck, 1)],
        "stats":             stats,
        "theme":             "",
        "bracket":           0,
        "bracket_label":     "",
        "art_style":         "",
        "model_speed":       "quality",
        "frame_style":       "builtin",
        "deck_slug":         deck_slug,
        "is_commander_deck": req.is_commander_deck,
        "generate_art":      False,
        # imported_only: saved from an import with no AI art yet. Drives the "original art"
        # display + the "Generate art / Retheme" affordance; cleared once a build/retheme runs.
        "imported":          True,
        "imported_only":     True,
        "import_source":     imp.source,
        "import_name":       imp.name,
        "import_source_input": req.source.strip(),
        "import_unresolved": imp.unresolved,
        "import_auto_face":  face_auto,
        # A saved import has no theme yet, so nothing to carry into a later art run —
        # but the art knobs must exist, because Retheme reads them from the source
        # deck. generate_art:False here is what used to make "save now, generate art
        # later" produce no art at all; the retheme request can now override it.
        "gen_settings":      {},
        "theme_spec":        {},
        "creativity":        "balanced",
        "built_at":          time.time(),
    }
    (state.RENDER_DIR / job_id / "deck.json").write_text(json.dumps(payload), encoding="utf-8")
    return {
        "job_id":        job_id,
        "name":          imp.name,
        "total_cards":   stats.get("total_cards"),
        "unresolved":    imp.unresolved,
        "imported_only": True,
    }


@router.post("/api/commander/search")
def search_commander(req: SearchRequest):
    card = _scryfall.get_card_by_name(req.query, fuzzy=True)
    if not card:
        raise HTTPException(404, f"Commander not found: {req.query}")
    return {
        "name":         card.get("_front_name") or card["name"],
        "full_name":    card["name"],
        "mana_cost":    card.get("mana_cost", ""),
        "type_line":    card.get("type_line", "").split(" // ")[0],
        "oracle_text":  card.get("oracle_text", ""),
        "colors":       card.get("color_identity", []),
        "image_url":    (card.get("image_uris") or {}).get("normal", ""),
        "legal":        card.get("legalities", {}).get("commander") in ("legal", "restricted"),
        # Which command-zone pairing ability this card has, if any. The UI shows its second
        # commander box only when this is non-null, so the 93% of commanders that cannot
        # partner never see a control they can't use.
        "partner":      commander_analysis.partner_mechanic(card),
    }


@router.get("/api/commander/autocomplete")
def autocomplete_commander(q: str = ""):
    """Return up to 10 card-name suggestions from Scryfall autocomplete."""
    if len(q.strip()) < 2:
        return {"suggestions": []}
    try:
        r = requests.get(
            "https://api.scryfall.com/cards/autocomplete",
            params={"q": q, "include_extras": "false"},
            headers={"User-Agent": "MTGDeckBuilder/1.0", "Accept": "application/json"},
            timeout=5,
        )
        names = r.json().get("data", []) if r.ok else []
        return {"suggestions": names[:10]}
    except Exception:
        return {"suggestions": []}


@router.get("/api/decks")
async def list_decks():
    """Return summary of all decks saved to disk (done or checkpoint), newest first."""
    results = []
    for p in sorted(state.RENDER_DIR.glob("*/deck.json"),
                    key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data   = json.loads(p.read_text(encoding="utf-8"))
            job_id = p.parent.name
            status = data.get("status", "done")
            # Skip purely in-memory building jobs that haven't checkpointed yet.
            # "cancelled" is included — a cancelled build still has a valid partial
            # deck worth showing in history.
            if status not in ("done", "rendering", "cancelled"):
                continue
            cmd    = data.get("commander", {})
            # Thumbnail: prefer rendered commander art, fall back to scryfall
            thumb = None
            rkey  = cmd.get("render_key")
            if rkey and (p.parent / "cards" / f"{rkey}.png").exists():
                thumb = f"/api/deck/{job_id}/card-image/{rkey}"
            elif cmd.get("scryfall_img"):
                thumb = cmd["scryfall_img"]
            # Cached MythGauntlet measurement (POST /api/deck/{id}/measure) -> badge
            lm_pp = (((data.get("last_measure") or {}).get("simulation") or {})
                     .get("power_profile") or {})
            results.append({
                "job_id":           job_id,
                "commander_name":   cmd.get("original_name", ""),
                "themed_name":      cmd.get("themed_name", ""),
                "theme":            data.get("theme", ""),
                "commander_prompt": data.get("commander_prompt", ""),
                "bracket":          data.get("bracket", 0),
                "bracket_label":    data.get("bracket_label", ""),
                # PHYSICAL cards: an import aggregates duplicate basics into one entry
                # carrying `quantity`, so counting entries showed a 100-card deck as "75".
                "card_count":       (sum(c.get("quantity", 1) or 1 for c in data.get("deck", []))
                                     + 1 + len(data.get("partners") or [])),
                "built_at":         data.get("built_at"),
                "thumbnail":        thumb,
                "partial":          status in ("rendering", "cancelled"),
                "is_copy":          bool(data.get("is_copy")),
                "copied_from":      data.get("copied_from", ""),
                # Lineage. Retheme/rebuild/duplicate each write a NEW deck under a NEW
                # job id and record where they came from — but only `copied_from` was
                # ever exposed, so History showed a chain of derived decks as a pile of
                # near-identical entries with no relationship between them.
                "derived_from":     (data.get("rethemed_from") or data.get("rebuilt_from")
                                     or data.get("copied_from", "")),
                "derived_kind":     ("retheme" if data.get("rethemed_from")
                                     else "rebuild" if data.get("rebuilt_from")
                                     else "copy" if data.get("copied_from") else ""),
                "imported":         bool(data.get("imported")),
                # A single custom card is not a deck; History showed it as
                # "B0 · 1 cards" with no way to tell the two apart.
                "mode":             data.get("mode", ""),
                "single_card":      _is_single_card(data),
                "has_bible":        bool((data.get("world_bible") or {}).get("world")),
                "measured_bracket": lm_pp.get("bracket_estimate"),
                "measured_label":   lm_pp.get("bracket_label", ""),
                # PLAN_CLOCK Phase 4: the engine's own honesty flag for a bracket estimate
                # sitting on the Core/Upgraded (or Exhibition/Core) boundary it can't resolve
                # from the card list alone (see SimStrengthPanel.jsx's `bracket_plays_up`
                # banner). It was already fetched and cached here (`lm_pp` is the whole
                # persisted power_profile) but silently dropped on the way into this compact
                # badge — so a History/RecentDecks tile could show a bare "B2" for a deck the
                # engine itself says is honestly ambiguous, the exact failure mode this flag
                # exists to prevent, just on a surface nobody had checked yet.
                "measured_plays_up": bool(lm_pp.get("bracket_plays_up", False)),
            })
        except Exception:
            continue
    return results


@router.get("/api/playstyles")
async def get_playstyles():
    return [
        {"key": k, "label": PLAYSTYLES[k]["label"], "description": PLAYSTYLES[k]["description"]}
        for k in PLAYSTYLE_ORDER
    ]


@router.post("/api/deck/{job_id}/duplicate")
async def duplicate_deck(job_id: str):
    """
    Create an independent copy of a completed deck under a fresh job_id.

    Copies the entire RENDER_DIR/{job_id}/ tree (deck.json, card renders, set
    symbol) to RENDER_DIR/{new_job_id}/ and stamps the copy with a new
    built_at timestamp and metadata flags so it appears independently in
    history without affecting the source deck.

    Returns {"new_job_id": "...", "themed_name": "..."}.
    """
    _require_job_id(job_id)
    import shutil as _shutil

    src_dir  = state.RENDER_DIR / job_id
    src_json = src_dir / "deck.json"

    # Load source data — prefer disk file, fall back to in-memory job store
    if src_json.exists():
        data = json.loads(src_json.read_text(encoding="utf-8"))
    elif job_id in _jobs and _jobs[job_id].get("status") == "done":
        data = {k: v for k, v in _jobs[job_id].items() if k != "cancel_event"}
    else:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, f"Source deck not found: {job_id}")
        data = disk

    if data.get("status") not in ("done", "rendering"):
        raise HTTPException(400, "Source deck is not yet complete")

    new_job_id = uuid.uuid4().hex[:16]
    dst_dir    = state.RENDER_DIR / new_job_id

    # Copy the whole render directory (card images, set symbol, deck.json)
    if src_dir.exists():
        _shutil.copytree(str(src_dir), str(dst_dir))
    else:
        dst_dir.mkdir(parents=True, exist_ok=True)

    # Patch the metadata in the copied deck.json
    data["status"]      = "done"
    data["is_copy"]     = True
    data["copied_from"] = job_id
    data["built_at"]    = time.time()

    new_json = dst_dir / "deck.json"
    new_json.write_text(json.dumps(data), encoding="utf-8")

    # Register in the in-memory job store so the new deck is immediately queryable
    _jobs[new_job_id] = data

    themed_name = (data.get("commander") or {}).get("themed_name", "")
    return {"new_job_id": new_job_id, "themed_name": themed_name}


@router.delete("/api/deck/{job_id}")
async def delete_deck(job_id: str):
    """
    Permanently delete a deck's render directory and in-memory job entry.
    Safe to call on decks that are done or partial — will not delete a deck
    that is currently building (status == 'building').
    Returns {"ok": True, "job_id": job_id}.
    """
    import shutil as _shutil

    _require_job_id(job_id)   # this function rmtree's a path built from job_id

    # Refuse to delete an actively-building deck
    job = _jobs.get(job_id, {})
    if job.get("status") == "building":
        raise HTTPException(409, "Cannot delete a deck that is currently building")

    # Remove render directory from disk
    deck_dir = state.RENDER_DIR / job_id
    if deck_dir.exists():
        try:
            _shutil.rmtree(str(deck_dir))
        except Exception as e:
            logger.error("failed to remove deck directory for job %r", job_id, exc_info=e)
            raise HTTPException(500, "Failed to remove deck directory.")

    # Remove generated_art directory for this job if it exists
    for art_dir in state.ART_DIR.glob(f"*_{job_id[:8]}"):
        try:
            _shutil.rmtree(str(art_dir))
        except Exception:
            pass

    # Remove from in-memory stores
    _jobs.pop(job_id, None)
    _progress.pop(job_id, None)

    return {"ok": True, "job_id": job_id}


class BatchDeleteRequest(BaseModel):
    job_ids: List[str]


@router.post("/api/decks/delete-batch")
async def delete_decks_batch(req: BatchDeleteRequest):
    """
    Delete multiple decks at once.  Skips any deck that is currently building.
    Returns {"deleted": [...], "skipped": [...]}.
    """
    import shutil as _shutil

    deleted = []
    skipped = []

    for job_id in req.job_ids:
        job = _jobs.get(job_id, {})
        if job.get("status") == "building":
            skipped.append(job_id)
            continue

        deck_dir = state.RENDER_DIR / job_id
        if deck_dir.exists():
            try:
                _shutil.rmtree(str(deck_dir))
            except Exception:
                skipped.append(job_id)
                continue

        for art_dir in state.ART_DIR.glob(f"*_{job_id[:8]}"):
            try:
                _shutil.rmtree(str(art_dir))
            except Exception:
                pass

        _jobs.pop(job_id, None)
        _progress.pop(job_id, None)
        deleted.append(job_id)

    return {"deleted": deleted, "skipped": skipped}


@router.get("/api/deck/{job_id}")
async def get_deck(job_id: str):
    _require_job_id(job_id)
    job = _jobs.get(job_id)
    if not job:
        disk = _load_deck_from_disk(job_id)
        if disk:
            _jobs[job_id] = disk
            job = disk
        else:
            raise HTTPException(404, "Job not found")

    # A job can be in memory but have no deck data when a build was cancelled
    # before _jobs[job_id].update(result) ran (that only happens at the very end,
    # after rendering).  deck.json IS written early (before art gen starts), so
    # fall through to disk and merge — preserving the in-memory status so the
    # frontend still sees "cancelled" rather than the disk's "rendering"/"done".
    if "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if disk:
            saved_status = job.get("status")          # e.g. "cancelled"
            _jobs[job_id].update(disk)
            if saved_status:                           # put the real status back
                _jobs[job_id]["status"] = saved_status
            job = _jobs[job_id]

    # Accept any state that has a usable payload — done, cancelled mid-build,
    # or rendering. The client gets the partial deck plus a status flag so it
    # can show what was completed instead of a 409 dead-end.
    if job["status"] == "building":
        raise HTTPException(409, "Deck still building — listen on /events instead")
    if job["status"] == "error":
        raise HTTPException(409, f"Deck failed: {job.get('error', 'unknown error')}")
    # "done", "rendering", "cancelled" → return whatever we have on disk
    out = _annotate_owned(_serializable_job(job))
    lm = out.get("last_measure")
    if isinstance(lm, dict):
        current = await asyncio.to_thread(_engine_fingerprint)
        if current is not None:
            fp = (lm.get("simulation") or {}).get("model_fingerprint")
            out["last_measure"] = {**lm, "stale": fp != current}
    return out


@router.get("/api/deck/{job_id}/card-image/{render_key}")
async def deck_card_image(job_id: str, render_key: str):
    _require_job_id(job_id)
    cards_dir = state.RENDER_DIR / job_id / "cards"
    path = cards_dir / f"{render_key}.png"
    if path.exists():
        # No-store on partial builds so the browser refetches after regen.
        return FileResponse(path, media_type="image/png",
                            headers={"Cache-Control": "no-cache, must-revalidate"})
    # Legacy deck.json files saved render_key without the _NNN index. Fall
    # back to any indexed variant we can find for this card. Prevents 404s on
    # decks built before the indexed-key migration.
    if cards_dir.exists() and "_" not in render_key.rsplit("_", 1)[-1].lstrip("0"):
        # Try {render_key}_NNN.png variants
        for candidate in sorted(cards_dir.glob(f"{render_key}_*.png")):
            return FileResponse(candidate, media_type="image/png",
                                headers={"Cache-Control": "no-cache, must-revalidate"})
    # Also accept the reverse: client requested indexed key but only un-indexed
    # exists (rare, but happens if the client computes _000 for a legacy deck).
    if "_" in render_key:
        bare = render_key.rsplit("_", 1)[0]
        bare_path = cards_dir / f"{bare}.png"
        if bare_path.exists():
            return FileResponse(bare_path, media_type="image/png",
                                headers={"Cache-Control": "no-cache, must-revalidate"})
    # No AI render (e.g. a saved-but-un-themed imported deck): fall back to the card's
    # ORIGINAL Scryfall art so recalled imports still display. Look the card up in
    # deck.json by render_key and redirect to its stored image URL.
    dj = state.RENDER_DIR / job_id / "deck.json"
    if dj.exists():
        try:
            data = json.loads(dj.read_text(encoding="utf-8"))
        except Exception:
            data = None
        if data:
            cards = ([data.get("commander")] if data.get("commander") else []) + (data.get("deck") or [])
            for c in cards:
                if c and c.get("render_key") == render_key and c.get("scryfall_img"):
                    return RedirectResponse(c["scryfall_img"])
    raise HTTPException(404, "Card image not found")


_VIDEO_MEDIA_TYPES = {"mp4": "video/mp4", "webp": "image/webp", "gif": "image/gif"}


@router.get("/api/deck/{job_id}/card-video/{render_key}")
async def card_video_file(job_id: str, render_key: str):
    """Serve a card's looping animation (MP4 / WebP / GIF), whichever exists."""
    _require_job_id(job_id)
    videos = state.RENDER_DIR / job_id / "videos"
    for ext, media in _VIDEO_MEDIA_TYPES.items():   # mp4 preferred, then webp, gif
        path = videos / f"{render_key}.{ext}"
        if path.exists():
            return FileResponse(path, media_type=media,
                                headers={"Cache-Control": "no-cache, must-revalidate"})
    raise HTTPException(404, "Card video not found")


@router.get("/api/deck/{job_id}/set-symbol")
async def set_symbol_endpoint(job_id: str):
    _require_job_id(job_id)
    path = state.RENDER_DIR / job_id / "set_symbol.png"
    if not path.exists():
        raise HTTPException(404, "Set symbol not found")
    return FileResponse(path, media_type="image/png")


# ── Export endpoints ──────────────────────────────────────────────────────────

def _load_job_for_export(job_id: str) -> dict:
    """Return a usable job dict for export, loading from disk when needed.

    Mirrors the permissive status logic of GET /api/deck/{job_id}: accepts
    'done', 'rendering', and 'cancelled' (all have card data on disk).
    Raises HTTPException for 404, still-building, and error states.
    """
    job = _jobs.get(job_id)
    # Fall back to disk for old/evicted jobs (same as the deck GET endpoint)
    if not job or not job.get("commander"):
        disk = _load_deck_from_disk(job_id)
        if disk:
            if job:
                _jobs[job_id].update(disk)
                job = _jobs[job_id]
            else:
                job = disk
    if not job:
        raise HTTPException(404, "Deck not found")
    status = job.get("status", "")
    if status == "building":
        raise HTTPException(409, "Deck still building — try again once it finishes")
    if status == "error":
        raise HTTPException(409, f"Deck failed to build: {job.get('error', 'unknown error')}")
    # A single custom card is a "deck of one" (commander only, deck == []), so an
    # empty deck list is valid there — only require the commander in that mode.
    if not job.get("commander") or (not job.get("deck") and job.get("mode") != "single_card"):
        raise HTTPException(409, "Deck has no card data yet")
    return job


def _export_image_resolver(job_id: str):
    """Resolve the printable image for a card: rendered proxy, else Scryfall art.

    A deck imported and saved WITHOUT AI art has no rendered proxies at all, so the
    render-only lookup produced an empty ZIP / "No rendered card images found" —
    the one export a freshly-saved import most obviously wants. Falling back to the
    card's real printing keeps that deck printable, and mixed decks (some cards
    regenerated, some not) come out complete. Downloads are cached per job under
    `original/` so a re-export costs nothing.
    """
    render_dir   = state.RENDER_DIR / job_id
    original_dir = render_dir / "original"

    def _resolve(card: dict) -> Optional[Path]:
        key = card.get("render_key") or ""
        png = render_dir / "cards" / f"{key}.png"
        if png.exists():
            return png
        url = card.get("scryfall_img") or ""
        if not url or not key:
            return None
        # Scryfall serves JPEG for `normal`; keep the real extension so the ZIP's
        # filenames don't lie about what's inside them.
        ext = Path(urlparse(url).path).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        cached = original_dir / f"{key}{ext}"
        if cached.exists():
            return cached
        return _download_art_to(url, cached)

    return _resolve


# Exports are built fully in memory, so they are sent as one Response. They were
# StreamingResponse(io.BytesIO(data)), which iterates the buffer LINE BY LINE: a 12 MB
# ZIP went out as ~46k newline-split chunks and took ~55 s to download (built in 0.4 s).
@router.get("/api/deck/{job_id}/export/zip")
def export_zip(job_id: str):
    _require_job_id(job_id)
    job = _load_job_for_export(job_id)
    render_dir = state.RENDER_DIR / job_id
    try:
        data = build_zip(job["commander"], job["deck"], render_dir,
                         image_for=_export_image_resolver(job_id))
    except Exception as e:
        logger.error("ZIP export failed for job %r", job_id, exc_info=e)
        raise HTTPException(500, "ZIP export failed.")
    if len(data) < 40:   # empty zip — same guard export_videos already had
        # A custom card has no Scryfall printing to fall back on, so if its render
        # is missing there is nothing to put in the archive. Streaming a 22-byte
        # "successful" download instead of saying so is the worse failure.
        raise HTTPException(
            409, "No card images to export yet — generate the art first "
                 "(the card has no rendered proxy on disk).")
    single = _is_single_card(job)
    safe = "".join(c if c.isalnum() else "_" for c in job["commander"]["original_name"])[:30]
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="{safe}_{"card" if single else "deck"}.zip"'},
    )


@router.get("/api/deck/{job_id}/export/decklist")
def export_decklist(job_id: str):
    """The deck's ORIGINAL card names as plain text, in the format this app imports.

    The themed proxies are a rendering of a deck; this is the deck itself. It round-
    trips (paste it back into Import and you get the same 100 cards), which makes it
    both the portable copy for Moxfield/Archidekt and the way to VERIFY that a
    themed build still contains exactly the cards that went in. Quantities are the
    physical counts, so aggregated duplicate basics expand correctly.
    """
    _require_job_id(job_id)
    job  = _load_job_for_export(job_id)
    cmd  = job.get("commander") or {}
    deck = job.get("deck") or []
    lines: list[str] = []
    if cmd.get("original_name"):
        # Only a real Commander deck gets a Commander header — an auto-elected
        # display face is just a maindeck card and must re-import as one.
        if job.get("is_commander_deck", True) and not job.get("import_auto_face"):
            lines += [f"Commander: {cmd['original_name']}", ""]
        else:
            deck = [cmd] + list(deck)
    for c in deck:
        name = c.get("original_name") or ""
        if name:
            lines.append(f"{int(c.get('quantity', 1) or 1)} {name}")
    unresolved = job.get("import_unresolved") or []
    if unresolved:
        # Recorded as comments (the importer skips '#' lines) so the export is an
        # honest account of the source deck rather than a silently shorter one.
        lines += ["", f"# {len(unresolved)} card(s) from the source could not be "
                      "matched on Scryfall and are NOT in this deck:"]
        lines += [f"# {n}" for n in unresolved]
    body = "\n".join(lines) + "\n"
    safe = "".join(c if c.isalnum() else "_" for c in (cmd.get("original_name") or "deck"))[:30]
    return Response(
        content=body.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}_decklist.txt"'},
    )


@router.get("/api/deck/{job_id}/export/videos")
def export_videos(job_id: str):
    """ZIP of the deck's looping MP4 animations (only animated cards)."""
    _require_job_id(job_id)
    job = _load_job_for_export(job_id)
    render_dir = state.RENDER_DIR / job_id
    try:
        data = build_video_zip(job["commander"], job["deck"], render_dir)
    except Exception as e:
        logger.error("video export failed for job %r", job_id, exc_info=e)
        raise HTTPException(500, "Video export failed.")
    if len(data) < 40:   # empty zip
        raise HTTPException(404, "No animated cards in this deck")
    safe = "".join(c if c.isalnum() else "_" for c in job["commander"]["original_name"])[:30]
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}_videos.zip"'},
    )


@router.get("/api/deck/{job_id}/export/pdf")
def export_pdf(job_id: str):
    _require_job_id(job_id)
    job = _load_job_for_export(job_id)
    render_dir = state.RENDER_DIR / job_id
    try:
        data = build_pdf(job["commander"], job["deck"], render_dir,
                         image_for=_export_image_resolver(job_id))
    except Exception as e:
        logger.error("PDF export failed for job %r", job_id, exc_info=e)
        raise HTTPException(500, "PDF export failed.")
    safe = "".join(c if c.isalnum() else "_" for c in job["commander"]["original_name"])[:30]
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}_proxies.pdf"'},
    )


# ── 3D Commander Generation ───────────────────────────────────────────────────

def _push_3d(job_3d_id: str, event: str, data: str):
    msg = f"event: {event}\ndata: {data}\n\n"
    _3d_progress.setdefault(job_3d_id, []).append(msg)


def _run_3d_generation(job_3d_id: str, deck_job_id: str):
    """
    Background thread: run the full commander 3D pipeline.
    Resolves the commander's raw art, runs rembg + Hunyuan3D v2 + trimesh export.
    """
    try:
        _3d_jobs[job_3d_id]["status"] = "rmbg"

        # ── Locate commander raw art ──────────────────────────────────────────
        deck_data = _jobs.get(deck_job_id)
        if not deck_data:
            deck_path = state.RENDER_DIR / deck_job_id / "deck.json"
            if deck_path.exists():
                deck_data = json.loads(deck_path.read_text(encoding="utf-8"))
            else:
                raise ValueError(f"Deck job not found: {deck_job_id}")

        commander = deck_data.get("commander", {})
        original_name = commander.get("original_name", "")
        deck_slug     = deck_data.get("deck_slug", "")

        # Try FLUX-generated art first (raw art from generated_art/ dir)
        art_path: Optional[Path] = None
        if deck_slug and original_name:
            safe = "".join(c if c.isalnum() else "_" for c in original_name)[:48]
            candidate = state.ART_DIR / deck_slug / f"{safe}.png"
            if candidate.exists():
                art_path = candidate

        # Fallback: Scryfall image URL → download to temp file
        if art_path is None:
            scryfall_url = commander.get("scryfall_img", "")
            if scryfall_url:
                _push_3d(job_3d_id, "progress", json.dumps({
                    "step": "rmbg",
                    "msg":  "No generated art found — using Scryfall card art as source",
                }))
                tmp_dir = state.RENDER_DIR / deck_job_id
                tmp_dir.mkdir(parents=True, exist_ok=True)
                art_path = tmp_dir / "commander_scryfall_src.jpg"
                r = requests.get(scryfall_url, timeout=30, stream=True)
                r.raise_for_status()
                with open(art_path, "wb") as f:
                    for chunk in r.iter_content(65536):
                        f.write(chunk)
            else:
                raise ValueError("No commander art available (no FLUX art and no Scryfall URL)")

        _push_3d(job_3d_id, "progress", json.dumps({
            "step": "rmbg",
            "msg":  f"Source image: {art_path.name}",
        }))

        # ── Progress callback → SSE ───────────────────────────────────────────
        def _cb(msg: str):
            step = "rmbg"
            if "Hunyuan" in msg or "3D mesh" in msg or "workflow" in msg or "Generating" in msg or "Upload" in msg:
                step = "trellis"
                _3d_jobs[job_3d_id]["status"] = "trellis"
            elif "STL" in msg or "GLB" in msg or "Converting" in msg or "Exporting" in msg:
                step = "converting"
                _3d_jobs[job_3d_id]["status"] = "converting"
            _push_3d(job_3d_id, "progress", json.dumps({"step": step, "msg": msg}))

        # ── Run pipeline ──────────────────────────────────────────────────────
        output_dir = state.RENDER_DIR / deck_job_id
        stl_path = generate_commander_3d(
            art_path   = art_path,
            output_dir = output_dir,
            progress_cb = _cb,
        )

        _3d_jobs[job_3d_id]["status"]   = "done"
        _3d_jobs[job_3d_id]["stl_path"] = str(stl_path)
        _push_3d(job_3d_id, "done", json.dumps({
            "job_3d_id":   job_3d_id,
            "stl_url":     f"/api/deck/{deck_job_id}/commander-3d.stl",
            "size_bytes":  stl_path.stat().st_size,
        }))

    except Exception as e:
        _3d_jobs[job_3d_id]["status"] = "error"
        _3d_jobs[job_3d_id]["error"]  = str(e)
        _push_3d(job_3d_id, "error", json.dumps({"msg": str(e)}))
        traceback.print_exc()


@router.post("/api/deck/{job_id}/generate-3d")
async def start_3d_generation(job_id: str, background_tasks: BackgroundTasks):
    """
    Start async 3D model generation for the commander of a completed deck.
    Returns {job_3d_id} immediately; poll /api/deck/{job_id}/3d-status/{job_3d_id}.
    """
    _require_job_id(job_id)
    # Verify the deck exists
    deck_exists = (
        job_id in _jobs
        or (state.RENDER_DIR / job_id / "deck.json").exists()
    )
    if not deck_exists:
        raise HTTPException(status_code=404, detail=f"Deck job not found: {job_id}")

    # Health check — surface missing models with a clear message
    health = await asyncio.to_thread(Model3DGen.health_check)   # blocking probes
    if not health["ok"]:
        raise HTTPException(
            status_code=503,
            detail={
                "message": health["message"],
                "hint":    health["hint"],
                "missing": health.get("missing", []),
            },
        )

    job_3d_id = str(uuid.uuid4())
    _3d_jobs[job_3d_id] = {
        "status":       "pending",
        "deck_job_id":  job_id,
        "created_at":   time.time(),
    }

    background_tasks.add_task(_run_3d_generation, job_3d_id, job_id)
    return JSONResponse({"job_3d_id": job_3d_id})


@router.get("/api/deck/{job_id}/3d-status/{job_3d_id}")
async def stream_3d_status(job_id: str, job_3d_id: str, request: Request):
    """SSE stream for 3D generation progress."""
    _require_job_id(job_id)
    # An unknown id (never started, or lost in a server restart) used to stream nothing
    # forever, polling every 0.5 s. 404 at once, like the build stream does.
    if job_3d_id not in _3d_jobs:
        raise HTTPException(status_code=404, detail="3D job not found - start the 3D generation again")

    async def _gen():
        sent = 0
        while True:
            if await request.is_disconnected():
                break
            msgs = _3d_progress.get(job_3d_id, [])
            while sent < len(msgs):
                yield msgs[sent]
                sent += 1
            job = _3d_jobs.get(job_3d_id, {})
            if job.get("status") in ("done", "error"):
                msgs = _3d_progress.get(job_3d_id, [])
                while sent < len(msgs):
                    yield msgs[sent]
                    sent += 1
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/api/deck/{job_id}/commander-3d.stl")
async def download_commander_stl(job_id: str):
    """Serve the completed commander STL for download."""
    _require_job_id(job_id)
    stl_path = state.RENDER_DIR / job_id / "commander_3d.stl"
    if not stl_path.exists():
        raise HTTPException(status_code=404,
                            detail="STL not found — generate it first via /generate-3d")

    # Determine a nice download filename from the deck commander name
    deck_data = _jobs.get(job_id, {})
    if not deck_data:
        deck_path = state.RENDER_DIR / job_id / "deck.json"
        if deck_path.exists():
            deck_data = json.loads(deck_path.read_text(encoding="utf-8"))

    cmd_name = deck_data.get("commander", {}).get("themed_name", "commander")
    safe_cmd = "".join(c if c.isalnum() or c in "- " else "_" for c in cmd_name)[:40].strip()
    filename = f"{safe_cmd}_3D.stl"

    return FileResponse(
        stl_path,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
