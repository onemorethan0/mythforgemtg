"""Card/deck dict helpers shared by the build, rebuild, regen, retheme and animate
pipelines: deck.json card schema, provenance, mana-cost parsing, render keys, pips.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import requests
from fastapi import HTTPException

import card_renderer
import commander_analysis
import mana_pips
from api import state
from api.collection_data import _card_is_owned, _owned_names_cached
from api.models import SingleCardModel
from api.state import _jobs, _load_deck_from_disk, _push, _scryfall
from deck_builder import CARD_SOURCES, SOURCE_PREFER, SOURCE_SCRYFALL
from services import _ollama_loaded_models
from themer import ThemedCard

# ── User-name substitution helper ────────────────────────────────────────────

# Commander naming with the player's chosen "Your Name" lives in
# themer.compose_commander_name — it drops the original first name AND regenerates
# a creature-type-fitting title when the themed title leaked the original.


# ── Shared build-pipeline helpers ─────────────────────────────────────────────
# The four _run_* pipelines (build / rebuild / regen / retheme) share a large
# amount of boilerplate: serializing ThemedCards, reconstructing card dicts from
# stored deck.json, computing render keys, and the common error/cleanup blocks.
# These helpers hold that shared logic in one place.  They deliberately do NOT
# touch VRAM eviction, the _art_lock, or any threading order — that orchestration
# stays inline in each pipeline because its sequencing is subtle and per-pipeline.


# ── LLM backend label ─────────────────────────────────────────────────────────

def _llm_label() -> str:
    """Name of the LLM backend actually in use, for logs and UI progress.

    Every build message used to say "Ollama" regardless of backend, so a healthy
    llama.cpp run read as an Ollama run in the log viewer.
    """
    from themer import LLM_BACKEND
    return "llama.cpp" if LLM_BACKEND == "llamacpp" else "Ollama"

def _free_all_vram(job_id: str = "") -> None:
    """
    Fire-and-forget VRAM cleanup triggered on job cancel.

    Sends unload/eviction requests to ComfyUI and Ollama and returns
    immediately — deliberately does NOT poll/wait for VRAM to confirm.

    Why fire-and-forget instead of blocking?
      • _wait_for_comfyui_unload() polls for _VRAM_LLM_CLEAR_GB free,
        but CUDA's caching allocator keeps freed PyTorch pages resident until
        torch.cuda.empty_cache() completes, which may never drive vram_free above
        the threshold within _EVICT_MAX_WAIT (120 s) while ComfyUI holds models.
        That 120-second timeout IS the "long hang after cancel" the user sees.
      • We don't need to gate on VRAM here because nothing is about to load.
        The *next* build's own pre-flight gate (_wait_for_ollama_evict /
        _wait_for_vram) already confirms VRAM is clear before loading anything.
    """
    # Clear ComfyUI job queue first — interrupt stops the running step but
    # ComfyUI would immediately start the next queued job otherwise.
    try:
        requests.post(
            "http://127.0.0.1:8188/queue",
            json={"clear": True},
            timeout=5,
        )
    except Exception:
        pass
    # Ask ComfyUI to unload models and run gc (async from ComfyUI's side)
    try:
        requests.post(
            "http://127.0.0.1:8188/free",
            json={"unload_models": True, "free_memory": True},
            timeout=5,
        )
    except Exception:
        pass
    # Send LLM eviction request (fire-and-forget — no VRAM poll), backend-aware.
    from themer import LLM_BACKEND, LLM_BASE
    if LLM_BACKEND == "llamacpp":
        try:
            requests.post(f"{LLM_BASE}/api/models/unload", timeout=5)
        except Exception:
            pass
    else:
        loaded = _ollama_loaded_models()
        for m in loaded:
            for endpoint in ("/api/generate", "/api/chat"):
                try:
                    payload = (
                        {"model": m, "keep_alive": 0}
                        if endpoint == "/api/generate"
                        else {"model": m, "keep_alive": 0,
                              "messages": [{"role": "user", "content": ""}]}
                    )
                    requests.post(
                        f"http://127.0.0.1:11434{endpoint}",
                        json=payload,
                        timeout=5,
                    )
                except Exception:
                    pass


# ── Filename helper ──────────────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    """Convert a card name to a safe filesystem-friendly string."""
    return "".join(c if c.isalnum() else "_" for c in name)[:48]


# ── Oracle text self-reference helper ────────────────────────────────────────

def _replace_card_self_ref(oracle_text: str, original_name: str, themed_name: str) -> str:
    """
    Replace occurrences of a card's original name in its own oracle text with
    the themed name. Uses word boundaries for the first-name pass so a card
    named "Sol, ..." doesn't mangle unrelated words like "Solitude".
    Handles double-faced cards (name1 // name2) by replacing each face's
    short form individually.
    """
    if not oracle_text or not original_name or not themed_name:
        return oracle_text

    first_themed = themed_name.split(",")[0].strip()

    # Full-name replacement first
    result = oracle_text.replace(original_name, themed_name)

    # ── Double-faced cards ("Face A // Face B") ──────────────────────────────
    # Oracle text only ever refers to one face at a time using just that face's
    # name (or its pre-comma first part), never the combined "A // B" string.
    if " // " in original_name:
        for face in (f.strip() for f in original_name.split(" // ")):
            # Replace full face name literally
            result = result.replace(face, first_themed)
            # Replace pre-comma short form ("Aang, Master of Elements" → "Aang")
            face_short = face.split(",")[0].strip()
            if face_short and len(face_short) > 2 and face_short != face:
                result = re.sub(rf"\b{re.escape(face_short)}\b", first_themed, result)
            # Replace first-word short form for multi-word no-comma faces
            # ("Avatar Aang" → "Avatar" is used in "transform Avatar Aang" which
            #  the literal replace above catches; but standalone "Aang" in text
            #  needs the first-word pass when there's no comma)
            elif face_short and " " in face_short:
                first_word        = face_short.split()[0]
                first_themed_word = first_themed.split()[0]
                if len(first_word) > 2:
                    result = re.sub(rf"\b{re.escape(first_word)}\b", first_themed_word, result)
        return result

    # ── Single-faced cards ────────────────────────────────────────────────────
    # Short-form self-references — Scryfall oracle text uses an abbreviated form:
    #   • Comma-based names: just the pre-comma part ("Uro, Titan…" → "Uro attacks")
    #   • No-comma multi-word names: just the first word ("Kaalia of the Vast" → "Kaalia attacks")
    first_orig = original_name.split(",")[0].strip()
    if first_orig and len(first_orig) > 2:
        if first_orig != original_name:
            # Comma-based name — pre-comma part is a distinct short form
            result = re.sub(rf"\b{re.escape(first_orig)}\b", first_themed, result)
        elif " " in first_orig:
            # No-comma multi-word name — use only the first word of the themed
            # name so "Dante of the Vast" reads "Whenever Dante attacks"
            first_word        = first_orig.split()[0]
            first_themed_word = first_themed.split()[0]
            if len(first_word) > 2:
                result = re.sub(rf"\b{re.escape(first_word)}\b", first_themed_word, result)
    return result


def _themed_card_to_dict(tc: ThemedCard, deck_index: int = 0, has_render: bool = False) -> dict:
    """Serialize a ThemedCard to the deck.json card schema.

    The render_key embeds the deck index (000 for commander, 001+ for the rest)
    so duplicate card names get distinct keys.  Oracle text has the card's own
    name swapped for its themed name.
    """
    c = tc.card
    # Same tidy the renderer applies (drop "— Class" enchantment noise; never print
    # the themed name as the creature subtype) so deck.json + the UI list match the
    # printed proxy.
    _display_tl = card_renderer.clean_display_type_line(c, c.get("type_line", ""), tc.themed_name)
    return {
        "original_name": tc.original_name,
        "themed_name":   tc.themed_name,
        # True = the user owns a real copy (or it's a basic land); False = a proxy they'd
        # need to acquire. Powers the ownership badges in the deck view. Re-checked at
        # serve time (_annotate_owned) so it tracks collection edits.
        "owned":         _card_is_owned(tc.original_name, c.get("type_line", ""), _owned_names_cached()),
        "art_prompt":    tc.art_prompt,    # LLM-generated; treated as immutable
        "custom_prompt": "",               # user override (kept separate from art_prompt)
        "use_custom":    False,            # which prompt feeds generation
        "flavor_text":   tc.flavor_text,
        "mana_cost":     c.get("mana_cost", ""),
        "type_line":          _display_tl,
        "original_type_line": c.get("original_type_line") or c.get("type_line", ""),
        "oracle_text":   _replace_card_self_ref(
                             c.get("oracle_text", ""), tc.original_name, tc.themed_name
                         ),
        "cmc":           c.get("cmc", 0),
        "colors":        c.get("color_identity", []),
        "power":         c.get("power"),
        "toughness":     c.get("toughness"),
        # Planeswalkers. Dropped here for years, so the single-card designer's
        # Loyalty field went into the void: the renderer never saw it and the
        # printed proxy had no loyalty at all.
        "loyalty":       c.get("loyalty"),
        "rarity":        c.get("rarity", ""),     # drives the set-symbol metal colour
        "quantity":      c.get("quantity", 1),   # >1 for imported duplicate basics
        "scryfall_img":  (c.get("image_uris") or {}).get("normal", ""),
        "has_render":    has_render,
        "has_video":     False,            # set True once an MP4 animation is generated
        "render_key":    f"{_safe_name(tc.original_name)}_{deck_index:03d}",
    }


def _imported_card_to_stored(c: dict, deck_index: int) -> dict:
    """Serialize a raw imported (Scryfall) card into the deck.json card schema WITHOUT
    theming. Mirrors _themed_card_to_dict but keeps the original name, no art_prompt, and
    has_render=False — used by 'Save to library' so an imported deck persists and recalls
    with its ORIGINAL art (the card-image endpoint falls back to scryfall_img). A later
    Retheme regenerates from this exactly like any other saved deck."""
    name = c.get("name", "")
    _display_tl = card_renderer.clean_display_type_line(c, c.get("type_line", ""), name)
    return {
        "original_name": name,
        "themed_name":   name,             # un-themed: the UI shows the real card name
        "art_prompt":    "",
        "custom_prompt": "",
        "use_custom":    False,
        "flavor_text":   c.get("flavor_text", ""),
        "mana_cost":     c.get("mana_cost", ""),
        "type_line":          _display_tl,
        "original_type_line": c.get("original_type_line") or c.get("type_line", ""),
        "oracle_text":   c.get("oracle_text", ""),
        "cmc":           c.get("cmc", 0),
        "colors":        c.get("color_identity", []),
        "power":         c.get("power"),
        "toughness":     c.get("toughness"),
        "loyalty":       c.get("loyalty"),
        "rarity":        c.get("rarity", ""),
        "quantity":      c.get("quantity", 1),
        "scryfall_img":  (c.get("image_uris") or {}).get("normal", ""),
        "has_render":    False,
        "has_video":     False,
        "render_key":    f"{_safe_name(name)}_{deck_index:03d}",
    }


def _write_cancelled_deck(job_id: str, cmd_tc: ThemedCard, deck_tcs: list,
                          stats: dict, theme: str, generate_art: bool) -> None:
    """Persist a minimal cancelled deck.json + in-memory job.

    The build/retheme pipelines only write their full checkpoint AFTER theming
    (build) or AFTER art (retheme), so a cancel before that point would leave no
    deck.json at all — and the result view crashes on the missing card list.
    This writes just enough (the card list + a "cancelled" status) so the page
    renders the deck, with has_render backfilled from whatever was rendered so
    far (Scryfall art fills the rest). Mirrors the art-phase cancel handling.
    """
    cards_dir = state.RENDER_DIR / job_id / "cards"
    rendered = {fp.stem for fp in cards_dir.glob("*.png")} if cards_dir.exists() else set()

    def _has(tc: ThemedCard, idx: int) -> bool:
        return f"{_safe_name(tc.original_name)}_{idx:03d}" in rendered

    path = state.RENDER_DIR / job_id / "deck.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status":       "cancelled",
        "commander":    _themed_card_to_dict(cmd_tc, deck_index=0, has_render=_has(cmd_tc, 0)),
        "deck":         [_themed_card_to_dict(tc, deck_index=i, has_render=_has(tc, i))
                         for i, tc in enumerate(deck_tcs, 1)],
        "stats":        stats,
        "theme":        theme,
        "generate_art": generate_art,
        "built_at":     time.time(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    _jobs[job_id].update(payload)
    _jobs[job_id]["status"] = "cancelled"
    _push(job_id, "done", json.dumps({"job_id": job_id, "cancelled": True}))


def _stored_card_to_dict(d: dict) -> dict:
    """Reconstruct the internal card dict from a stored deck.json entry.

    Inverse of the card portion of _themed_card_to_dict — used by rebuild / regen
    / retheme to rebuild ThemedCard.card payloads from persisted decks.
    """
    return {
        "name":               d["original_name"],
        "mana_cost":          d.get("mana_cost", ""),
        "type_line":          d.get("type_line", ""),
        "original_type_line": d.get("original_type_line") or d.get("type_line", ""),
        "oracle_text":        d.get("oracle_text", ""),
        "cmc":            d.get("cmc", 0),
        "color_identity": d.get("colors", []),
        "power":          d.get("power"),
        "toughness":      d.get("toughness"),
        "loyalty":        d.get("loyalty"),
        "rarity":         d.get("rarity", ""),
        "quantity":       d.get("quantity", 1),
        "image_uris":     {"normal": d["scryfall_img"]} if d.get("scryfall_img") else {},
    }


def _stored_card_to_raw(d: dict) -> dict:
    """Stored deck.json entry → a card dict fit to be themed FROM SCRATCH.

    Same as `_stored_card_to_dict`, but rewinds the two fields a previous theming
    pass mutated: `type_line` goes back to the card's real printed line (a stored
    entry carries the tribe-RESKINNED line, e.g. "Creature — Holo-Priest") and
    `keywords` is cleared so the themer re-derives mechanics. Without the rewind, a
    re-theme whose new theme maps that type to nothing keeps the OLD theme's
    creature type printed on the card — a wrong card model on a deck the user never
    asked to change. The themer always reskins from `original_type_line`, so the
    rewind is a no-op on the path where a map DOES cover the type.
    """
    c = _stored_card_to_dict(d)
    c["type_line"] = d.get("original_type_line") or d.get("type_line", "")
    c["keywords"]  = []
    return c


# Fields that identify WHAT a deck is (as opposed to how it looks). Rebuild and
# retheme write a new deck.json under a NEW job id — the source is always left
# intact — so anything not copied across that boundary is silently lost.
_PROVENANCE_KEYS = (
    "imported", "import_source", "import_name", "import_source_input",
    "import_unresolved", "import_auto_face", "is_commander_deck",
    "face_assignments", "partners",
    # A single custom card IS a "deck of one", and `mode` is the only thing that
    # says so. Losing it across a rebuild/retheme turned the user's card into a
    # deck with zero cards: the result screen showed deck stats, type filters and
    # an empty gallery, History listed it as "B0 · 1 cards", and every export
    # 409'd on `_load_job_for_export`'s empty-deck guard. `theme_mode` travels
    # with it because a re-theme must not rename a card the user authored.
    "mode", "theme_mode", "art_prompt_mode", "user_flavor",
)


def _carry_provenance(dst: dict, src: dict, *, generated_art: bool) -> dict:
    """Copy a source deck's identity/provenance onto a derived deck's payload.

    Losing `imported` here is not cosmetic: Edit & Rebuild reads it to decide
    whether to reuse the stored card list or generate a fresh one, so a rethemed
    import that forgot the flag would silently regenerate into a DIFFERENT deck on
    the next edit. `is_commander_deck` / `face_assignments` decide which cards get
    a face, and dropping them stamps the commander portrait onto a 60-card list's
    auto-elected display card.

    `imported_only` means "an import with no AI art yet"; it survives a text-only
    re-run and clears the moment a run actually produces art.
    """
    for k in _PROVENANCE_KEYS:
        if k in src:
            dst[k] = src[k]
    if src.get("imported_only") and not generated_art:
        dst["imported_only"] = True
    else:
        dst.pop("imported_only", None)
    return dst


def _is_single_card(data: dict) -> bool:
    """Is this deck.json a single custom card (a 'deck of one')?

    One predicate, used everywhere. `mode` is the real flag; `playstyle` is
    checked too because it was the only single-card marker that happened to
    survive a rebuild/retheme before `mode` joined `_PROVENANCE_KEYS`, and those
    already-derived decks on disk should heal rather than stay broken. Deliberately
    NOT structural (`deck == []`): a build cancelled during theming also has an
    empty deck, and calling that a custom card would be a worse mistake.
    """
    d = data or {}
    return d.get("mode") == "single_card" or d.get("playstyle") == "Single Card"


def _preserve_decklist(themed_deck: list, raw_deck: list[dict]) -> list:
    """Guarantee a theming pass returned exactly the cards it was given.

    Theming re-invents names and art prompts — it must NEVER change WHICH cards are
    in the deck. If a themer returned a short or partial list, rebuild it from
    `raw_deck` (by original name, in order), filling gaps with plain-named cards.
    A no-op on the normal path; the point is that an imported paper decklist can
    never come back with a card missing or substituted.
    """
    if len(themed_deck) == len(raw_deck):
        return themed_deck
    print(f"  [theme] themer returned {len(themed_deck)} of {len(raw_deck)} cards "
          f"— backfilling the rest with plain names so the decklist is preserved")
    by_orig = {tc.original_name: tc for tc in themed_deck}
    out = []
    for c in raw_deck:
        n = c.get("name") or c.get("original_name") or ""
        out.append(by_orig.get(n, ThemedCard(n, n, "", "", c)))
    return out


_MANA_SYMBOL_RE = re.compile(r"\{([^}]+)\}")
_WUBRG = ("W", "U", "B", "R", "G")


_SHORTHAND_MANA_RE = re.compile(r"\d+|[WUBRGCXYZS]", re.I)


def _normalize_mana_cost(mana_cost: str) -> str:
    """Accept a mana cost typed WITHOUT braces and return the canonical form.

    Everything downstream — cmc, colour identity, the pip renderer, the frame
    colour — is driven by ``{...}`` symbols, so a perfectly reasonable-looking
    entry like ``2WU`` used to parse as ZERO symbols: the card came out
    colourless, mana value 0, with a blank cost row and a grey artifact frame,
    and nothing anywhere said why. A brace-free string is unambiguous, so
    normalize it instead of silently dropping it.

    Only fires when the string contains no ``{``; a braced cost is the user's
    (they may be writing hybrids/phyrexians we shouldn't second-guess), and an
    unparseable brace-free string is returned untouched rather than mangled.
    """
    raw = (mana_cost or "").strip()
    if not raw or "{" in raw:
        return raw
    compact = raw.replace(" ", "").replace("/", "")
    if not compact:
        return raw
    parts = _SHORTHAND_MANA_RE.findall(compact)
    # Every character must be accounted for, else this isn't a mana cost.
    if "".join(parts) != compact:
        return raw
    return "".join("{" + p.upper() + "}" for p in parts)


def _parse_mana_cost(mana_cost: str) -> tuple[float, list[str]]:
    """Derive (cmc, color_identity) from a mana-cost string like '{2}{W}{U}'.

    Generic numbers add to cmc; X = 0; a hybrid symbol is worth the HIGHEST of
    its halves (rule 202.3b), so {2/W} is 2 while {W/U} and the phyrexian {W/P}
    are 1. Every WUBRG letter a symbol names joins the colour identity.
    """
    cmc = 0.0
    colors: list[str] = []
    for sym in _MANA_SYMBOL_RE.findall(mana_cost or ""):
        s = sym.upper().strip()
        if s in ("X", "Y", "Z"):
            continue
        if s.isdigit():
            cmc += int(s)
            continue
        # Hybrid/phyrexian: worth the largest of its halves, never less than 1.
        halves = [h.strip() for h in s.split("/")]
        cmc += max([int(h) for h in halves if h.isdigit()] + [1])
        for letter in _WUBRG:
            if letter in s and letter not in colors:
                colors.append(letter)
    # preserve WUBRG order
    colors = [c for c in _WUBRG if c in colors]
    return cmc, colors


def _single_card_to_internal(m: "SingleCardModel") -> dict:
    """Build the internal card dict the theming/render pipeline expects from a
    user-authored SingleCardModel. Derives cmc + color identity from the mana
    cost when the user didn't pin colours explicitly."""
    mana_cost = _normalize_mana_cost(m.mana_cost)
    cmc, derived_colors = _parse_mana_cost(mana_cost)
    colors = [c.upper() for c in (m.colors or []) if c] or derived_colors
    name = (m.name or "").strip() or "Custom Card"
    rarity = (m.rarity or "rare").strip().lower()
    return {
        "name":               name,
        "mana_cost":          mana_cost,
        "type_line":          m.type_line or "",
        "original_type_line": m.type_line or "",
        "oracle_text":        m.oracle_text or "",
        "flavor_text":        m.flavor_text or "",
        "cmc":            cmc,
        "color_identity": colors,
        "colors":         colors,
        "power":          (m.power if (m.power not in (None, "")) else None),
        "toughness":      (m.toughness if (m.toughness not in (None, "")) else None),
        "loyalty":        (m.loyalty if (m.loyalty not in (None, "")) else None),
        "rarity":         rarity,
        "quantity":       1,
        "image_uris":     {},
    }


def _load_source_deck(source_job_id: str) -> dict:
    """Load a saved deck.json by job id (memory path first, then disk loader).

    Raises ValueError if no deck can be found — callers rely on this to abort.
    """
    source_path = state.RENDER_DIR / source_job_id / "deck.json"
    if source_path.exists():
        data = json.loads(source_path.read_text(encoding="utf-8"))
    else:
        data = _load_deck_from_disk(source_job_id)
    if not data:
        raise ValueError(f"Source deck not found: {source_job_id}")
    return data


def _build_render_keys(themed_cmd: ThemedCard, themed_deck: list) -> dict:
    """Map each card's original_name → indexed render key (commander = 000)."""
    keys = {themed_cmd.original_name: f"{_safe_name(themed_cmd.original_name)}_000"}
    for i, tc in enumerate(themed_deck, 1):
        keys[tc.original_name] = f"{_safe_name(tc.original_name)}_{i:03d}"
    return keys


def _setup_deck_pips(job_id: str, enabled: bool, art_theme: str, subject: str,
                     source_job_id: str = ""):
    """
    Install (or clear) themed custom mana pips for a deck render.

    Pips are a per-deck override of the stock W/U/B/R/G/C symbols: a mana-colour
    disc with a single shared black silhouette of the deck's icon. The SAME
    silhouette is reused to build the deck's set emblem so it actually reflects
    the requested subject. Generated once per deck and saved under <job>/pips/.
    On rebuild/regen/retheme the source deck's pips are reused so the silhouette
    stays identical across operations. Must be called in every render path;
    passing enabled=False clears any override left by a previous build (state is
    module-global in card_renderer).

    Returns the freshly-built set-emblem PIL image when pips are generated this
    call (so the build can swap in the matching emblem), else None.
    """
    if not enabled:
        card_renderer.set_custom_pips(None)
        return None
    pip_dir = state.RENDER_DIR / job_id / "pips"

    # Reuse the source deck's pips (keeps the silhouette identical on re-renders).
    # The source set_symbol.png already carries the matching emblem, so callers
    # keep their copied symbol — return None here.
    if source_job_id:
        existing = mana_pips.load_mana_pips(state.RENDER_DIR / source_job_id / "pips")
        if existing:
            pip_dir.mkdir(parents=True, exist_ok=True)
            for code, img in existing.items():
                img.save(pip_dir / f"pip_{code}.png", "PNG")
            card_renderer.set_custom_pips(existing)
            return None

    # Already generated for this job (e.g. resumed render)?
    existing = mana_pips.load_mana_pips(pip_dir)
    if existing:
        card_renderer.set_custom_pips(existing)
        return None

    _push(job_id, "progress", json.dumps(
        {"step": "pips", "msg": "Generating custom mana pips…"}))
    try:
        _, silhouette = mana_pips.save_mana_pips(art_theme, pip_dir, subject or art_theme)
        card_renderer.set_custom_pips(mana_pips.load_mana_pips(pip_dir))
        # Build a set emblem from the same silhouette and overwrite the procedural
        # one so the deck symbol matches the requested subject + the pips.
        emblem = mana_pips.make_set_emblem(silhouette, art_theme)
        emblem.save(state.RENDER_DIR / job_id / "set_symbol.png", "PNG")
        return emblem
    except Exception as e:
        print(f"  [pips] generation failed, using stock symbols: {e}")
        card_renderer.set_custom_pips(None)
        return None


def _make_art_progress_cb(job_id: str, start_time: float):
    """Build the per-card art progress callback used by build/rebuild.

    Computes a rolling ETA from wall-clock average per completed card and pushes
    an SSE 'art' progress event.
    """
    def _cb(card_num, total, card_name, has_face, elapsed, success):
        wall_elapsed = time.time() - start_time
        avg_secs = wall_elapsed / card_num if card_num else elapsed
        _push(job_id, "progress", json.dumps({
            "step":      "art",
            "msg":       f"[{card_num}/{total}] {card_name}",
            "card_num":  card_num,
            "total":     total,
            "card_name": card_name,
            "has_face":  has_face,
            "pct":       round(card_num / total * 100, 1) if total else 0,
            "elapsed":   round(wall_elapsed),
            "eta":       round(avg_secs * (total - card_num)),
            "last_ok":   success,
        }))
    return _cb


def _download_art_to(url: str, dest: "Path") -> Optional["Path"]:
    """Download a Scryfall card image to dest. Returns dest or None.

    The User-Agent is REQUIRED, not politeness: Scryfall's image CDN answers a
    default `python-requests/...` UA with HTTP 400 `generic_user_agent`, and this
    helper's only signal for that was returning None — so every download here failed
    silently (verified against cards.scryfall.io: 400 bare, 200 with a UA).
    """
    if not url:
        return None
    try:
        import requests as _rq
        r = _rq.get(url, timeout=20, headers={
            "User-Agent": "MythForge/1.3 (personal MTG proxy tool)",
            "Accept": "image/*",
        })
        if r.status_code == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
            return dest
        print(f"  [art] download refused HTTP {r.status_code} ({url}): {r.text[:160]}")
    except Exception as e:
        print(f"  [art] download failed ({url}): {e}")
    return None


def _resolve_card_source(card_source: str, use_collection: bool) -> str:
    """Which pool the builder may draft from.

    `card_source` wins when it names a known mode. An empty/unknown value falls back to
    the legacy boolean so every caller predating this field keeps its exact behaviour:
    use_collection=True has always meant PREFER owned, never "owned only", and
    redefining it would silently narrow existing users' decks."""
    src = (card_source or "").strip().lower()
    if src in CARD_SOURCES:
        return src
    return SOURCE_PREFER if use_collection else SOURCE_SCRYFALL


def _resolve_partners(lead: dict, names: list[str] | None) -> list[dict]:
    """Resolve second-commander names and REFUSE an illegal pairing.

    Refusing matters more than it looks: the command zone's colour identity filters every
    other card in the deck, so an illegal pair does not produce a slightly-wrong deck, it
    produces 99 cards chosen against an identity that is not legal to play. A deck the user
    has to fix beats one that cannot be registered.
    """
    out: list[dict] = []
    for raw in (names or []):
        name = (raw or "").strip()
        if not name:
            continue
        card = _scryfall.get_card_by_name(name, fuzzy=True)
        if not card:
            raise HTTPException(404, f"Partner not found: {name}")
        ok, why = commander_analysis.can_pair(lead, card)
        if not ok:
            raise HTTPException(400, why)
        out.append(card)

    # A duplicate name isn't a legal pairing (the same card can't occupy the command
    # zone twice), and every non-lead partner must ALSO be legally pairable with every
    # other non-lead partner — checking each against the lead alone would admit e.g. two
    # cards that can each partner with the lead but not with each other.
    seen: set[str] = set()
    for card in out:
        key = (card.get("name") or "").casefold()
        if key in seen:
            raise HTTPException(400, f"{card.get('name', 'That card')} can't be paired with itself.")
        seen.add(key)
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            ok, why = commander_analysis.can_pair(out[i], out[j])
            if not ok:
                raise HTTPException(400, why)
    return out
