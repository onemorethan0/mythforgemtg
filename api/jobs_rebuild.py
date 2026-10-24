"""Rebuild worker: re-roll a deck's art from its stored prompts into a new job.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

import card_renderer
from api import state
from api.cards import (
    _build_render_keys,
    _carry_provenance,
    _llm_label,
    _load_source_deck,
    _make_art_progress_cb,
    _setup_deck_pips,
    _stored_card_to_dict,
    _themed_card_to_dict,
)
from api.models import (
    RebuildRequest,
    _gen_settings_to_dict,
    _resolve_gen_settings_reusing,
)
from api.state import _art_lock, _finalize_job, _jobs, _mark_job_error, _push
from card_renderer import render_card, render_deck_thumbnails
from face_ref import get_face_paths
from image_gen import ImageGen
from services import (
    _ensure_comfyui_ready,
    _wait_for_comfyui_unload,
    _wait_for_ollama_evict,
)
from set_symbol import generate_set_symbol
from themer import ThemedCard

# ── Rebuild: re-run art gen for an already-themed deck ───────────────────────

def _run_rebuild(job_id: str, source_job_id: str, req: RebuildRequest):
    """
    Re-generate card art + re-render frames for an existing themed deck.

    Skips commander lookup, deck construction, and Ollama theming — uses the
    art_prompt strings already saved in the source deck.json.  New random seeds
    are used each time so every rebuild produces visually distinct images.
    """
    import shutil as _shutil

    try:
        _jobs[job_id]["status"] = "building"

        # ── Load source deck ──────────────────────────────────────────────────
        source_data = _load_source_deck(source_job_id)

        _push(job_id, "progress", json.dumps({"step": "deck", "msg": "Loading saved deck and prompts…"}))

        # Reconstruct ThemedCard objects from stored card dicts
        def _dict_to_tc(d: dict) -> ThemedCard:
            return ThemedCard(
                original_name = d["original_name"],
                themed_name   = d["themed_name"],
                art_prompt    = d.get("art_prompt", ""),
                flavor_text   = d.get("flavor_text", ""),
                card          = _stored_card_to_dict(d),
            )

        themed_cmd  = _dict_to_tc(source_data["commander"])
        themed_deck = [_dict_to_tc(c) for c in source_data["deck"]]
        art_theme   = source_data.get("theme", "")
        stats       = source_data.get("stats", {})

        prompt_count = sum(1 for c in source_data["deck"] if c.get("art_prompt"))
        _push(job_id, "progress", json.dumps({
            "step": "deck",
            "msg":  f"Loaded {len(themed_deck)} cards — {prompt_count} have saved art prompts",
        }))

        # ── Set symbol: reuse from source if available ────────────────────────
        render_out = state.RENDER_DIR / job_id / "cards"
        render_out.mkdir(parents=True, exist_ok=True)
        sym_path = state.RENDER_DIR / job_id / "set_symbol.png"

        old_sym = state.RENDER_DIR / source_job_id / "set_symbol.png"
        if old_sym.exists():
            _shutil.copy2(old_sym, sym_path)
            from PIL import Image as _PIL
            sym = _PIL.open(sym_path)
        else:
            _push(job_id, "progress", json.dumps({"step": "symbol", "msg": "Regenerating set symbol…"}))
            sym = generate_set_symbol(art_theme, emblem_prompt=source_data.get("emblem_prompt", ""))
            sym.save(sym_path)

        # Reuse the source deck's custom pips (if it had them) for a consistent look.
        _rebuild_pips = bool(source_data.get("custom_pips", False))
        _setup_deck_pips(job_id, _rebuild_pips, art_theme,
                         source_data.get("emblem_prompt", ""), source_job_id)
        card_renderer.set_frame_style(source_data.get("frame_style", "builtin"))

        cancel_event = _jobs[job_id].get("cancel_event") or threading.Event()

        # Compute a new deck_slug for the rebuild's art cache directory
        _rebuild_deck_slug = ("".join(c if c.isalnum() else "_" for c in themed_cmd.original_name)[:28]
                              + "_" + job_id[:8])

        # ── Write checkpoint ─────────────────────────────────────────────────
        deck_json_path = state.RENDER_DIR / job_id / "deck.json"
        checkpoint = {
            "status":           "rendering",
            "commander":        _themed_card_to_dict(themed_cmd, deck_index=0),
            "deck":             [_themed_card_to_dict(tc, deck_index=i) for i, tc in enumerate(themed_deck, 1)],
            "stats":            stats,
            "theme":            art_theme,
            "theme_spec":       source_data.get("theme_spec", {}),
            "creativity":       source_data.get("creativity", "balanced"),
            "commander_prompt": source_data.get("commander_prompt", ""),
            "emblem_prompt":    source_data.get("emblem_prompt", ""),
            "playstyle":        source_data.get("playstyle", ""),
            "collection":       source_data.get("collection"),  # C4 badge survives rebuild
            "bracket":          source_data.get("bracket", 3),
            "bracket_label":    source_data.get("bracket_label", ""),
            "art_style":        req.art_style,
            "model_speed":      req.model_speed,
            # Carry forward the gen settings used for this rebuild (request override
            # or the source deck's persisted set) so later regens keep them.
            "gen_settings":     _gen_settings_to_dict(req.gen_settings) or source_data.get("gen_settings", {}),
            "generate_art":     True,
            "deck_slug":        _rebuild_deck_slug,
            "face_key":         req.face_key or source_data.get("face_key", ""),
            "face_gender":      req.face_gender or source_data.get("face_gender", "either"),
            "crew_key":         req.crew_key or source_data.get("crew_key", ""),
            "crew_gender":      req.crew_gender or source_data.get("crew_gender", "either"),
            "border_theme":     source_data.get("border_theme", ""),
            "frame_style":      source_data.get("frame_style", "builtin"),
            "commander_tribe":  source_data.get("commander_tribe", ""),
            "tribal_overrides": source_data.get("tribal_overrides", {}),
            # Carried so a later Edit restores the user's explicit picks (not the
            # merged auto-map) and the deck view keeps its Set Bible / player name.
            "user_tribal_overrides": source_data.get("user_tribal_overrides", {}),
            "auto_theme_tribes": bool(source_data.get("auto_theme_tribes", True)),
            "world_bible":      source_data.get("world_bible", {}) or {},
            "user_name":        source_data.get("user_name", ""),
            "llm_model":        source_data.get("llm_model", ""),
            "custom_pips":      _rebuild_pips,
            "rebuilt_from":     source_job_id,
            "built_at":         time.time(),
        }
        # A rebuild re-rolls art on the SAME cards — the deck's identity is unchanged,
        # so it must survive the new-job boundary. See _carry_provenance.
        _carry_provenance(checkpoint, source_data, generated_art=True)
        deck_json_path.write_text(json.dumps(checkpoint), encoding="utf-8")

        # ── Art generation ────────────────────────────────────────────────────
        art_paths: dict[str, Optional[Path]] = {}

        # Pre-build a fallback art_paths from the source deck's existing FLUX art.
        # Used when ComfyUI is unavailable so the rebuild can preserve previously
        # generated art instead of falling all the way back to Scryfall images.
        # Walks up the rebuilt_from/rethemed_from chain to find actual art files
        # even when intermediate rebuilds didn't generate art.
        def _collect_art_from_slug(slug: str) -> dict[str, Optional[Path]]:
            """Return {original_name: path} for all art PNGs in generated_art/{slug}/."""
            result: dict[str, Optional[Path]] = {}
            if not slug:
                return result
            art_dir = state.ART_DIR / slug
            for _tc in [themed_cmd] + list(themed_deck):
                _safe = "".join(ch if ch.isalnum() else "_" for ch in _tc.original_name)[:48]
                _p = art_dir / f"{_safe}.png"
                if _p.exists():
                    result[_tc.original_name] = _p
            return result

        def _find_ancestor_art(data: dict, depth: int = 0) -> tuple[dict, str]:
            """Walk rebuilt_from/rethemed_from chain, return first non-empty art dict + slug."""
            if depth > 5:
                return {}, ""
            slug = data.get("deck_slug", "")
            found = _collect_art_from_slug(slug)
            if found:
                return found, slug
            # Try parent deck
            parent_id = data.get("rebuilt_from") or data.get("rethemed_from")
            if parent_id:
                parent_path = state.RENDER_DIR / parent_id / "deck.json"
                if parent_path.exists():
                    try:
                        parent_data = json.loads(parent_path.read_text(encoding="utf-8"))
                        return _find_ancestor_art(parent_data, depth + 1)
                    except Exception:
                        pass
            return {}, ""

        _fallback_art, _fallback_slug = _find_ancestor_art(source_data)

        if _fallback_art:
            _push(job_id, "progress", json.dumps({
                "step": "art",
                "msg":  f"Found {len(_fallback_art)} existing art file(s) (from {_fallback_slug}) — will reuse if new art gen is skipped.",
            }))

        # Auto-start ComfyUI if down (no-op if already up / not locatable).
        _ensure_comfyui_ready(job_id)
        health = ImageGen.health_check()
        if not health["ok"]:
            _fallback_msg = (
                f"Reusing {len(_fallback_art)} existing art images from {_fallback_slug}."
                if _fallback_art else
                "No existing art found — cards will use Scryfall images."
            )
            _push(job_id, "progress", json.dumps({
                "step":    "art",
                "msg":     f"⚠ ComfyUI not available — {health['message']}. {_fallback_msg}",
                "warning": True,
                "hint":    "Start ComfyUI before rebuilding to generate new art.",
            }))
            art_paths = _fallback_art  # reuse source art rather than going straight to Scryfall
            # Emit a progress event so the UI shows movement before rendering starts
            _push(job_id, "progress", json.dumps({
                "step": "art",
                "msg":  "Proceeding to render card frames with fallback art…",
            }))
        else:
            # Evict Ollama from VRAM and confirm before loading models.
            from image_gen import _is_flux
            from themer import OLLAMA_MODEL as _DEFAULT_OLLAMA
            _evict_rt = source_data.get("llm_model") or _DEFAULT_OLLAMA

            # For non-FLUX models (SDXL, SD3.5), unload ComfyUI FIRST so the
            # subsequent Ollama-eviction VRAM gate can actually pass.  With FLUX
            # still resident in ComfyUI (~12 GB) the gate never reaches 16 GB and
            # wastes the full 120-second timeout before giving up.
            if req.checkpoint and not _is_flux(req.checkpoint):
                _push(job_id, "progress", json.dumps({"step": "art", "msg": "Unloading previous ComfyUI models for VRAM headroom…"}))
                _wait_for_comfyui_unload(job_id)

            _push(job_id, "progress", json.dumps({"step": "art", "msg": f"Evicting {_llm_label()} ({_evict_rt}) from VRAM…"}))
            _wait_for_ollama_evict(_evict_rt, job_id)

            _push(job_id, "progress", json.dumps({"step": "art", "msg": "Waiting for GPU…"}))
            with _art_lock:
                try:
                    gen = ImageGen(model_speed=req.model_speed, art_style=req.art_style,
                                  checkpoint=req.checkpoint,
                                  gen_settings=_resolve_gen_settings_reusing(req.gen_settings, source_data),
                                  frame_style=source_data.get("frame_style", "builtin"))
                except Exception as _ge:
                    _push(job_id, "progress", json.dumps({
                        "step": "art",
                        "msg":  f"⚠ Art generation skipped — ImageGen init failed: {_ge}",
                        "warning": True,
                    }))
                    gen = None

                if gen is not None and gen.available:
                    deck_slug = _rebuild_deck_slug

                    # Resolve commander face (req overrides stored value)
                    # CRITICAL FIX: Validate that face photos still exist before generation.
                    # If photos were deleted/moved, fall back to no face conditioning to avoid
                    # generic "torches on black background" artifacts from FLUX getting None paths.
                    _face_key = req.face_key or source_data.get("face_key", "")
                    face_paths: list[Path] = []
                    if _face_key:
                        face_paths = get_face_paths(_face_key)
                        if face_paths:
                            # Verify paths still exist
                            valid_face_paths = [p for p in face_paths if p.exists()]
                            if valid_face_paths and len(valid_face_paths) < len(face_paths):
                                _push(job_id, "progress", json.dumps({
                                    "step": "art",
                                    "msg":  f"⚠ {len(face_paths) - len(valid_face_paths)} face photo(s) missing, using {len(valid_face_paths)}",
                                    "warning": True,
                                }))
                                face_paths = valid_face_paths
                            elif not valid_face_paths:
                                _push(job_id, "progress", json.dumps({
                                    "step": "art",
                                    "msg":  f"⚠ Face key '{_face_key}' has no valid photos, skipping face conditioning",
                                    "warning": True,
                                }))
                                face_paths = []
                            elif valid_face_paths:
                                _push(job_id, "progress", json.dumps({
                                    "step": "art",
                                    "msg":  f"Commander face: {len(valid_face_paths)} photo(s) — {gen.face_method_label}",
                                }))

                    # Resolve crew faces (same validation)
                    _crew_key = req.crew_key or source_data.get("crew_key", "")
                    crew_paths: list[Path] = []
                    if _crew_key:
                        crew_paths = get_face_paths(_crew_key)
                        if crew_paths:
                            valid_crew_paths = [p for p in crew_paths if p.exists()]
                            if valid_crew_paths and len(valid_crew_paths) < len(crew_paths):
                                print(f"  [rebuild] Crew photos: {len(valid_crew_paths)}/{len(crew_paths)} valid")
                                crew_paths = valid_crew_paths
                            elif not valid_crew_paths:
                                print(f"  [rebuild] Crew key '{_crew_key}' has no valid photos")
                                crew_paths = []
                            elif valid_crew_paths:
                                _push(job_id, "progress", json.dumps({
                                    "step": "art",
                                    "msg":  f"Crew photos: {len(valid_crew_paths)} photo(s) for creature cards",
                                }))

                    _push(job_id, "progress", json.dumps({"step": "art", "msg": "Generating card art (ComfyUI)…"}))
                    _art_start_time = time.time()

                    _art_cb = _make_art_progress_cb(job_id, _art_start_time)

                    def _card_done_cb(tc, art_path):
                        name = tc.original_name
                        safe = "".join(ch if ch.isalnum() else "_" for ch in name)[:48]
                        out_path = render_out / f"{safe}.png"
                        if not out_path.exists():
                            try:
                                from PIL import Image as _PILImage
                                art_img  = _PILImage.open(art_path) if art_path and art_path.exists() else None
                                card_img = render_card(
                                    tc.card, tc.themed_name,
                                    tc.card.get("oracle_text", ""),
                                    art_image=art_img,
                                    set_symbol=sym,
                                    border_theme=source_data.get("border_theme", ""),
                                )
                                card_img.save(out_path, "PNG")
                            except Exception as _re:
                                print(f"  [render-inline] {name}: {_re}")
                        if out_path.exists():
                            _push(job_id, "card_ready", json.dumps({"key": safe, "name": tc.themed_name}))

                    _face_gender = req.face_gender or source_data.get("face_gender", "either")
                    _crew_gender = req.crew_gender or source_data.get("crew_gender", "either")
                    _crew_prompt = (req.crew_prompt if req.crew_prompt is not None
                                    else source_data.get("crew_prompt", "")) or ""
                    try:
                        art_paths = gen.generate_deck(
                            themed_cmd, themed_deck, deck_slug,
                            face_paths=face_paths or None,
                            crew_paths=crew_paths or None,
                            face_gender=_face_gender,
                            crew_gender=_crew_gender,
                            crew_prompt=_crew_prompt,
                            progress_callback=_art_cb,
                            theme_str=art_theme,
                            card_done_callback=_card_done_cb,
                            cancel_event=cancel_event,
                            # Who gets a face is a property of the DECK, not of this
                            # run — see the same note in _run_retheme.
                            is_commander_deck=bool(
                                source_data.get("is_commander_deck", True)),
                            face_assignments=(
                                source_data.get("face_assignments") or None),
                        )
                    except Exception as _ge_err:
                        _push(job_id, "progress", json.dumps({
                            "step": "art",
                            "msg":  f"⚠ Art generation aborted: {_ge_err}",
                            "warning": True,
                        }))
                        traceback.print_exc()

                    # ── Per-card fallback: patch failed cards with ancestor art ───
                    _patched = 0
                    for _card_name, _art_path in list(art_paths.items()):
                        if _art_path is None and _card_name in _fallback_art:
                            art_paths[_card_name] = _fallback_art[_card_name]
                            _patched += 1
                    if _patched:
                        _push(job_id, "progress", json.dumps({
                            "step": "art",
                            "msg":  f"Patched {_patched} failed card(s) with previous FLUX art.",
                            "warning": True,
                        }))

                    if not any(p for p in art_paths.values()):
                        if _fallback_art:
                            art_paths = _fallback_art
                            _push(job_id, "progress", json.dumps({
                                "step":    "art",
                                "msg":     f"⚠ ComfyUI produced no art — reusing {len(_fallback_art)} existing art images from previous build.",
                                "warning": True,
                                "hint":    "Check ComfyUI's console for errors. Existing FLUX art preserved.",
                            }))
                        else:
                            _push(job_id, "progress", json.dumps({
                                "step":    "art",
                                "msg":     "⚠ No art generated and no existing art found — falling back to Scryfall art for all cards.",
                                "warning": True,
                                "hint":    "Check ComfyUI's console for errors.",
                            }))

        # ── Early-exit on cancel ──────────────────────────────────────────────
        # Skip VRAM freeing and render if cancelled (same reason as in /api/deck/build).
        # Let the background task (_free_all_vram) handle VRAM cleanup exclusively.
        if cancel_event.is_set():
            _jobs[job_id]["status"] = "cancelled"
            try:
                if deck_json_path.exists():
                    _d = json.loads(deck_json_path.read_text(encoding="utf-8"))
                    _d["status"] = "cancelled"
                    deck_json_path.write_text(json.dumps(_d), encoding="utf-8")
            except Exception:
                pass
            _push(job_id, "done", json.dumps({"job_id": job_id, "cancelled": True}))
            return

        # ── Release FLUX VRAM after rebuild art gen ───────────────────────────
        _wait_for_comfyui_unload(job_id)

        # ── Render card frames ────────────────────────────────────────────────
        _push(job_id, "progress", json.dumps({"step": "render", "msg": "Rendering card frames…"}))
        # In rebuild, oracle_text in tc.card is already processed; flavor from tc.flavor_text
        _all_tcs_rb = [themed_cmd] + list(themed_deck)
        _oracle_ov_rb = {tc.original_name: tc.card.get("oracle_text", "") for tc in _all_tcs_rb}
        _flavor_ov_rb = {tc.original_name: tc.flavor_text or "" for tc in _all_tcs_rb}
        _render_keys_rb = _build_render_keys(themed_cmd, themed_deck)
        saved_imgs = render_deck_thumbnails(
            themed_cmd, themed_deck, art_theme, art_paths, render_out,
            oracle_overrides=_oracle_ov_rb,
            flavor_overrides=_flavor_ov_rb,
            border_theme=source_data.get("border_theme", ""),
            render_keys=_render_keys_rb,
        )
        _push(job_id, "progress", json.dumps({"step": "render", "msg": f"Rendered {len(saved_imgs)} card frames"}))

        # ── Finalize ──────────────────────────────────────────────────────────
        result = dict(checkpoint)
        result["status"]    = "done"
        result["commander"] = _themed_card_to_dict(themed_cmd, deck_index=0, has_render=themed_cmd.original_name in saved_imgs)
        result["deck"]      = [_themed_card_to_dict(tc, deck_index=i, has_render=tc.original_name in saved_imgs) for i, tc in enumerate(themed_deck, 1)]
        _jobs[job_id].update(result)
        deck_json_path.write_text(json.dumps(result), encoding="utf-8")

        _push(job_id, "done", json.dumps({"job_id": job_id}))

    except Exception as e:
        _mark_job_error(job_id, e)
    finally:
        _finalize_job(job_id)
