"""Per-card workers: regenerate selected cards' art, and animate cards.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Optional

import card_renderer
from api import state
from api.cards import (
    _download_art_to,
    _llm_label,
    _load_source_deck,
    _setup_deck_pips,
    _stored_card_to_dict,
)
from api.models import (
    AnimateCardsRequest,
    RegenCardsRequest,
    _resolve_gen_settings_reusing,
)
from api.state import (
    _art_lock,
    _finalize_job,
    _get_deck_regen_lock,
    _jobs,
    _mark_job_error,
    _push,
)
from card_renderer import render_card
from face_ref import get_face_paths
from image_gen import ImageGen
from services import (
    _ensure_comfyui_ready,
    _wait_for_comfyui_unload,
    _wait_for_ollama_evict,
)
from themer import ThemedCard

# ── Per-card regen: regenerate only the requested cards ──────────────────────

def _run_regen_cards(job_id: str, source_job_id: str, req: RegenCardsRequest):
    """
    Generate new art for a specific subset of cards in an existing deck.

    Writes rendered PNGs directly into the SOURCE job's cards/ directory so the
    existing deck view can refresh individual tiles without reloading the whole deck.
    Pushes ``card_ready`` events (with ``source_job_id``) after each card renders.
    If custom prompts were supplied, updates the source deck.json art_prompt fields
    so the changes persist for future rebuilds.

    Holds a per-source-deck lock for the entire run so concurrent regen calls
    on the same deck queue up rather than racing PNG writes / SSE events.
    """
    from PIL import Image as _PIL

    # Per-deck serialization gate — see _get_deck_regen_lock docstring.
    _deck_lock = _get_deck_regen_lock(source_job_id)
    _deck_lock.acquire()

    try:
        _jobs[job_id]["status"] = "building"

        # ── Load source deck ──────────────────────────────────────────────────
        # source_json_path is kept for the custom-prompt write-back near the end.
        source_json_path = state.RENDER_DIR / source_job_id / "deck.json"
        source_data = _load_source_deck(source_job_id)

        # Index by render_key and by original_name for robust matching
        all_stored = [source_data["commander"]] + source_data["deck"]
        key_map:  dict[str, dict] = {}
        name_map: dict[str, dict] = {}
        for cd in all_stored:
            safe = "".join(ch if ch.isalnum() else "_" for ch in cd["original_name"])[:48]
            key_map[safe] = cd
            if cd.get("render_key"):
                key_map[cd["render_key"]] = cd   # also index by the full _NNN-suffixed key
            name_map[cd["original_name"]] = cd

        # ── Build target list ─────────────────────────────────────────────────
        # Tuple: (tc, render_key, art_safe, has_custom)
        #   render_key  — full key from deck.json (e.g. "Inquisitor_Greyfax_000"), used as
        #                 the output PNG filename so it overwrites the existing card image.
        #   art_safe    — bare sanitised name (no _NNN suffix), used only for the
        #                 generated_art/ cache path to avoid collisions across rebuilds.
        to_regen: list[tuple[ThemedCard, str, str, bool]] = []
        for entry in req.cards:
            cd = key_map.get(entry.render_key) or name_map.get(entry.original_name)
            if not cd:
                _push(job_id, "progress", json.dumps({
                    "step": "art",
                    "msg":  f"⚠ Card not found: {entry.original_name} — skipping",
                }))
                continue

            art_safe = "".join(ch if ch.isalnum() else "_" for ch in cd["original_name"])[:48]
            # Use the deck.json render_key (includes _NNN index) so the saved PNG
            # overwrites the original rendered file and the card_ready event key
            # matches what the frontend stores in card.render_key / refreshTs.
            stored_render_key = cd.get("render_key") or art_safe
            # Pick which prompt feeds generation. The LLM art_prompt is the default
            # and is NEVER overwritten; the custom prompt is used only when the card
            # is flagged use_custom and has custom text. The request is authoritative
            # (custom text falls back to whatever was previously stored for the card).
            custom = (entry.custom_prompt if entry.custom_prompt is not None
                      else cd.get("custom_prompt", "")) or ""
            custom = custom.strip()
            use_custom = bool(entry.use_custom and custom)
            prompt = (custom if use_custom else cd.get("art_prompt", "")) \
                     or cd.get("art_prompt", "") or cd["original_name"]

            # RO decks: a CUSTOM regen prompt is the user's own text, so it lacks the
            # element/race/class tokens a build bakes in. Apply the same treatment so
            # per-card re-classing/accessorizing works (e.g. type "Monk class, cowboy
            # hat" to re-class one card). Stored (non-custom) prompts already have them.
            if use_custom and source_data.get("art_style") == "ragnarok_online":
                from themer import apply_ro_tokens as _apply_ro
                prompt = _apply_ro(prompt, _stored_card_to_dict(cd), override_text=custom)

            tc = ThemedCard(
                original_name = cd["original_name"],
                themed_name   = cd["themed_name"],
                art_prompt    = prompt,
                flavor_text   = cd.get("flavor_text", ""),
                card          = _stored_card_to_dict(cd),
            )
            to_regen.append((tc, stored_render_key, art_safe, bool(custom)))

        if not to_regen:
            raise ValueError("No matching cards found to regenerate")

        n = len(to_regen)
        _push(job_id, "progress", json.dumps({
            "step": "art",
            "msg":  f"Regenerating {n} card{'' if n == 1 else 's'}…",
        }))

        art_theme  = source_data.get("theme", "")
        sym_path   = state.RENDER_DIR / source_job_id / "set_symbol.png"
        sym        = _PIL.open(sym_path) if sym_path.exists() else None

        # Reuse the source deck's custom pips so regenerated cards match the rest.
        _setup_deck_pips(source_job_id, bool(source_data.get("custom_pips", False)),
                         art_theme, source_data.get("emblem_prompt", ""))
        card_renderer.set_frame_style(source_data.get("frame_style", "builtin"))

        # Renders go directly into the SOURCE job's cards/ dir
        render_out = state.RENDER_DIR / source_job_id / "cards"
        render_out.mkdir(parents=True, exist_ok=True)

        # Which card is the commander — face conditioning applies only to it
        commander_original_name = source_data.get("commander", {}).get("original_name", "")

        # Effective face/crew settings: request overrides stored deck values
        effective_face_key    = req.face_key  or source_data.get("face_key")  or ""
        effective_face_gender = req.face_gender or source_data.get("face_gender") or "either"
        effective_crew_key    = req.crew_key  or source_data.get("crew_key")  or ""
        effective_crew_gender = req.crew_gender or source_data.get("crew_gender") or "either"

        # ── ComfyUI pre-flight ────────────────────────────────────────────────
        # Auto-start ComfyUI if down (regen needs it — wait for it to load).
        _ensure_comfyui_ready(job_id)
        health = ImageGen.health_check()
        if not health["ok"]:
            raise ValueError(f"ComfyUI not available: {health['message']}")

        # Evict Ollama from VRAM and confirm before loading models.
        from image_gen import _is_flux
        from themer import OLLAMA_MODEL as _DEFAULT_OLLAMA
        _evict_rg = source_data.get("llm_model") or _DEFAULT_OLLAMA

        # For non-FLUX models (SDXL, SD3.5), unload ComfyUI FIRST so the
        # subsequent Ollama-eviction VRAM gate can actually pass.  With FLUX
        # still resident in ComfyUI (~12 GB) the gate never reaches 16 GB and
        # wastes the full 120-second timeout before giving up.
        if req.checkpoint and not _is_flux(req.checkpoint):
            _push(job_id, "progress", json.dumps({"step": "art", "msg": "Unloading previous ComfyUI models for VRAM headroom…"}))
            _wait_for_comfyui_unload(job_id)

        _push(job_id, "progress", json.dumps({"step": "art", "msg": f"Evicting {_llm_label()} ({_evict_rg}) from VRAM…"}))
        _wait_for_ollama_evict(_evict_rg, job_id)

        cancel_event = _jobs[job_id].get("cancel_event") or threading.Event()

        _push(job_id, "progress", json.dumps({"step": "art", "msg": "Waiting for GPU…"}))
        with _art_lock:
            gen = ImageGen(model_speed=req.model_speed, art_style=req.art_style,
                          checkpoint=req.checkpoint,
                          gen_settings=_resolve_gen_settings_reusing(req.gen_settings, source_data),
                          frame_style=source_data.get("frame_style", "builtin"))
            if not gen.available:
                raise ValueError("ComfyUI not available after acquiring GPU lock")

            # Unique art-cache slug per regen run → never hits the file-exists cache
            first_tc = to_regen[0][0]
            deck_slug = (
                "".join(c if c.isalnum() else "_" for c in first_tc.original_name)[:20]
                + "_regen_" + job_id[:8]
            )

            # Upload commander face (applied only to commander card)
            face_comfy_name_for_cmd: Optional[str] = None
            commander_in_batch = any(
                tc.original_name == commander_original_name for tc, _, _, _ in to_regen
            )
            if commander_in_batch and effective_face_key and gen.face_method != "none":
                _fp = get_face_paths(effective_face_key)
                if _fp:
                    face_comfy_name_for_cmd = gen.upload_face_to_comfy(_fp[0])
                    _push(job_id, "progress", json.dumps({
                        "step": "art",
                        "msg":  f"Commander face loaded ({gen.face_method_label})",
                    }))
                else:
                    _push(job_id, "progress", json.dumps({
                        "step": "art",
                        "msg":  "⚠ Commander face key found but photos missing",
                    }))

            # Upload all crew photos (applied round-robin to humanoid creature cards)
            crew_comfy_names: list[str] = []
            if effective_crew_key and gen.face_method != "none":
                _cp = get_face_paths(effective_crew_key)
                for cp in _cp:
                    n = gen.upload_face_to_comfy(cp)
                    if n:
                        crew_comfy_names.append(n)
                if crew_comfy_names:
                    _push(job_id, "progress", json.dumps({
                        "step": "art",
                        "msg":  f"Crew photos loaded: {len(crew_comfy_names)} photo(s) for creature cards",
                    }))

            # Upload the FORCE face — applied to every selected card regardless of
            # type (the user explicitly wants this likeness on the card(s) they
            # picked, so it bypasses the commander/humanoid routing below).
            force_face_comfy_name: Optional[str] = None
            if req.force_face_key:
                if gen.face_method == "none":
                    _push(job_id, "progress", json.dumps({
                        "step": "art",
                        "msg":  "⚠ A face was supplied but no face-swap node is installed — install PuLID / IP-Adapter / ReActor in ComfyUI to apply it",
                    }))
                else:
                    _ff = get_face_paths(req.force_face_key)
                    if _ff:
                        force_face_comfy_name = gen.upload_face_to_comfy(_ff[0])
                        _push(job_id, "progress", json.dumps({
                            "step": "art",
                            "msg":  f"Forced face loaded ({gen.face_method_label}) — applied to all {len(to_regen)} selected card(s)",
                        }))
                    else:
                        _push(job_id, "progress", json.dumps({
                            "step": "art",
                            "msg":  "⚠ Force-face key supplied but photos missing",
                        }))

            _art_start   = time.time()
            total        = len(to_regen)
            crew_regen_idx = 0   # round-robin index for crew faces
            # Render keys whose still art was regenerated this run — their existing
            # animation (if any) now depicts the OLD art, so it's invalidated below.
            regen_done_keys: set[str] = set()

            from image_gen import route_card_face as _route_face

            # Face routing is a property of the DECK — a non-Commander import has no
            # hero, and an import with explicit per-card assignments must not fall
            # back to the humanoid round-robin. Regen used to hardcode both, so
            # re-rolling one card put the commander portrait on a 60-card list's
            # display card, or a crew face on a card the user never assigned.
            _is_cmd_deck   = bool(source_data.get("is_commander_deck", True))
            _assignments   = source_data.get("face_assignments") or None

            for i, (tc, render_key, art_safe, has_custom) in enumerate(to_regen, 1):
                if cancel_event.is_set():
                    break

                # Face conditioning. Priority:
                #   1. Forced face → every selected card, any type (user's explicit pick).
                #   2. Otherwise the deck's own routing (route_card_face): commander
                #      hero, explicit per-card assignment, or crew round-robin.
                is_commander = tc.original_name == commander_original_name
                if force_face_comfy_name:
                    face_for_card   = force_face_comfy_name
                    gender_for_card = req.force_face_gender or "either"
                else:
                    face_for_card, gender_for_card, _uses_crew, crew_regen_idx = _route_face(
                        is_cmd=is_commander,
                        is_commander_deck=_is_cmd_deck,
                        commander_face=face_comfy_name_for_cmd,
                        crew_faces=crew_comfy_names,
                        face_gender=effective_face_gender,
                        crew_gender=effective_crew_gender,
                        card_type_line=tc.card.get("type_line", ""),
                        card_name=tc.original_name,
                        face_assignments=_assignments,
                        crew_idx=crew_regen_idx,
                    )

                wall = time.time() - _art_start
                eta  = round(wall / i * (total - i)) if i > 1 else 0
                _push(job_id, "progress", json.dumps({
                    "step":      "art",
                    "msg":       f"[{i}/{total}] {tc.themed_name}",
                    "card_num":  i, "total": total,
                    "card_name": tc.themed_name,
                    "has_face":  face_for_card is not None,
                    "pct":       round(i / total * 100, 1),
                    "elapsed":   round(wall), "eta": eta,
                    "last_ok":   None,
                }))

                t0 = time.time()
                art_path = gen.generate(
                    tc.art_prompt,
                    str(state.ART_DIR / deck_slug / art_safe),
                    face_comfy_name=face_for_card,
                    face_gender=gender_for_card,
                    card_type=tc.card.get("type_line", ""),
                )
                elapsed = time.time() - t0
                success = art_path is not None

                _push(job_id, "progress", json.dumps({
                    "step":      "art",
                    "msg":       f"[{i}/{total}] {tc.themed_name} — {'OK' if success else 'FAIL'}",
                    "card_num":  i, "total": total,
                    "card_name": tc.themed_name,
                    "has_face":  face_for_card is not None,
                    "pct":       round(i / total * 100, 1),
                    "elapsed":   round(time.time() - _art_start),
                    "eta":       round(elapsed * (total - i)),
                    "last_ok":   success,
                }))

                if success:
                    out_path = render_out / f"{render_key}.png"
                    try:
                        art_img  = _PIL.open(art_path) if art_path.exists() else None
                        card_img = render_card(
                            tc.card, tc.themed_name,
                            tc.card.get("oracle_text", ""),
                            art_image=art_img,
                            set_symbol=sym,
                            # Regen re-renders the WHOLE card, not just the art, so
                            # omitting the flavor text silently erased it from the
                            # printed proxy every time the user re-rolled art.
                            flavor_text=tc.flavor_text or "",
                            border_theme=source_data.get("border_theme", ""),
                        )
                        card_img.save(out_path, "PNG")
                        # Stash the new RAW art crop as this slot's CURRENT art so a
                        # later Animate uses the regenerated version, not the original
                        # build crop. The motion (I2V) path needs the raw crop, not the
                        # composite; keyed by render_key it overrides the stale build
                        # crop in generated_art/<deck_slug>/. (Foil already uses the
                        # composite card PNG we just overwrote above.)
                        try:
                            if art_path and art_path.exists():
                                import shutil as _shutil
                                _cur_art_dir = state.RENDER_DIR / source_job_id / "art"
                                _cur_art_dir.mkdir(parents=True, exist_ok=True)
                                _shutil.copyfile(art_path, _cur_art_dir / f"{render_key}.png")
                        except OSError as _ce:
                            print(f"  [regen] could not stash current art for {render_key}: {_ce}")
                        # The new still invalidates any prior animation (it was made
                        # from the OLD art). Delete the stale clip so the tile shows
                        # the fresh still until the user re-animates.
                        _video_was_cleared = False
                        for _ext in ("mp4", "webp", "gif"):
                            _vp = state.RENDER_DIR / source_job_id / "videos" / f"{render_key}.{_ext}"
                            if _vp.exists():
                                try:
                                    _vp.unlink()
                                    _video_was_cleared = True
                                except OSError:
                                    pass
                        regen_done_keys.add(render_key)
                        _push(job_id, "card_ready", json.dumps({
                            "key":           render_key,
                            "name":          tc.themed_name,
                            "source_job_id": source_job_id,
                            # Tell the UI to drop any stale animation for this tile.
                            "video_cleared": _video_was_cleared,
                        }))
                    except Exception as _re:
                        print(f"  [regen] render failed for {tc.themed_name}: {_re}")

        # ── Early-exit on cancel ─────────────────────────────────────────────
        if cancel_event.is_set():
            _jobs[job_id]["status"] = "cancelled"
            _push(job_id, "done", json.dumps({"job_id": job_id, "cancelled": True}))
            return

        # ── Persist custom prompts + the use-custom choice to deck.json ──────
        # IMPORTANT: never overwrite the LLM-generated art_prompt — store the user's
        # text in a separate custom_prompt field so both remain available and the
        # original can always be recovered. Records the per-card use_custom flag too.
        prompt_updates = {
            "".join(ch if ch.isalnum() else "_" for ch in e.original_name)[:48]: e
            for e in req.cards
        }
        if prompt_updates or regen_done_keys:
            updated = dict(source_data)

            def _patch_prompt(cd):
                safe = "".join(ch if ch.isalnum() else "_" for ch in cd["original_name"])[:48]
                rk   = cd.get("render_key") or safe
                e    = prompt_updates.get(safe)
                stale_video = rk in regen_done_keys
                if not e and not stale_video:
                    return cd
                patched = dict(cd)
                if e:
                    patched["use_custom"] = bool(e.use_custom)
                    # Only replace stored custom text when new text was supplied;
                    # an empty/None custom_prompt preserves whatever was there.
                    if e.custom_prompt is not None and e.custom_prompt.strip():
                        patched["custom_prompt"] = e.custom_prompt.strip()
                # A regenerated still invalidates its animation (made from old art).
                if stale_video:
                    patched.pop("has_video", None)
                    patched.pop("video_meta", None)
                return patched

            updated["commander"] = _patch_prompt(updated["commander"])
            updated["deck"]      = [_patch_prompt(c) for c in updated["deck"]]
            source_json_path.write_text(json.dumps(updated), encoding="utf-8")

            # Keep in-memory copy consistent
            if source_job_id in _jobs and isinstance(_jobs[source_job_id].get("deck"), list):
                _jobs[source_job_id]["commander"] = updated["commander"]
                _jobs[source_job_id]["deck"]      = updated["deck"]

        # Mark terminal status BEFORE the done event. Without this the job stays
        # "building" forever (the /status poll and the active-build lock both read
        # _jobs[job_id]["status"]), even though the art + render already completed.
        _jobs[job_id]["status"] = "done"
        _push(job_id, "done", json.dumps({"job_id": job_id, "source_job_id": source_job_id}))

    except Exception as e:
        _mark_job_error(job_id, e)
    finally:
        # Release the per-deck regen lock before any other cleanup so a queued
        # concurrent regen on the same deck doesn't wait on this thread's
        # bookkeeping work.
        try:
            _deck_lock.release()
        except RuntimeError:
            pass   # already released or never acquired — best-effort
        _finalize_job(job_id)


def _run_animate_cards(job_id: str, source_job_id: str, req: "AnimateCardsRequest"):
    """
    Animate a subset of cards: run a ComfyUI image-to-video model on each card's
    still ART, recomposite every frame through the static card chrome
    (card_renderer.render_card_frames), and encode a looping MP4 into the SOURCE
    job's videos/ dir. Pushes ``video_ready`` per card and persists has_video /
    video_meta to deck.json. Mirrors _run_regen_cards (same per-deck lock, GPU
    handoff, SSE channel).
    """
    from pathlib import Path as _Path

    from PIL import Image as _PIL

    import card_video

    def _safe(n: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in n)[:48]

    _deck_lock = _get_deck_regen_lock(source_job_id)
    _deck_lock.acquire()
    try:
        _jobs[job_id]["status"] = "building"
        source_json_path = state.RENDER_DIR / source_job_id / "deck.json"
        source_data = _load_source_deck(source_job_id)

        all_stored = [source_data["commander"]] + source_data["deck"]
        key_map: dict[str, dict] = {}
        name_map: dict[str, dict] = {}
        for cd in all_stored:
            key_map[_safe(cd["original_name"])] = cd
            if cd.get("render_key"):
                key_map[cd["render_key"]] = cd
            name_map[cd["original_name"]] = cd

        targets = []
        for entry in req.cards:
            cd = key_map.get(entry.render_key) or name_map.get(entry.original_name)
            if cd:
                targets.append(cd)
            else:
                _push(job_id, "progress", json.dumps({
                    "step": "video", "msg": f"⚠ Card not found: {entry.original_name} — skipping"}))
        if not targets:
            raise ValueError("No matching cards found to animate")

        # ── Effect / output-format setup ──────────────────────────────────────
        do_motion = req.effect in ("motion", "motion_foil")
        do_foil   = req.effect in ("foil", "motion_foil")
        fmt = (req.fmt or "mp4").lower()
        if fmt not in card_video.VIDEO_FORMATS:
            fmt = "mp4"

        # ── ComfyUI + video-model preflight (only the I2V motion path needs it;
        #    the procedural foil sheen runs on CPU with no model) ───────────────
        method = None
        if do_motion:
            _ensure_comfyui_ready(job_id)
            vh = card_video.health_check()
            if not vh["ok"]:
                raise ValueError(f"Animation model unavailable: {vh['message']} {vh['hint']}")

            from themer import OLLAMA_MODEL as _DEFAULT_OLLAMA
            _push(job_id, "progress", json.dumps({"step": "video", "msg": "Evicting LLM from VRAM…"}))
            _wait_for_ollama_evict(source_data.get("llm_model") or _DEFAULT_OLLAMA, job_id)
            method = req.method or card_video.detect_method()
            if not method:
                raise ValueError("No image-to-video model available in ComfyUI")

        # ── Effective frame-rate + clip length ────────────────────────────────
        # fps falls back to the I2V method default (foil-only → 24). A requested
        # `duration` (seconds) is converted to a frame count — snapped to the
        # model's preferred k*n+1 for I2V motion, or round(s*fps) for the foil
        # sweep. An explicit `frames` override still wins; None → downstream default.
        eff_fps = int(req.fps or (card_video._VIDEO_METHODS[method]["fps"] if method else 24))
        if req.frames:
            eff_frames = int(req.frames)
        elif req.duration:
            eff_frames = card_video.frames_for_duration(
                method, req.duration, eff_fps, foil=not do_motion)
        else:
            eff_frames = None
        foil_intensity = (float(req.foil_intensity)
                          if req.foil_intensity is not None else 0.55)
        motion_strength = (float(req.motion_strength)
                           if req.motion_strength is not None
                           else card_video.MOTION_STRENGTH_DEFAULT)
        # Loop style for art motion: crossfade (default, forward-only) / bounce
        # (ping-pong) / off. Foil is inherently periodic and always encoded "off".
        eff_loop_style = card_video._resolve_loop_style(req.loop, req.loop_style)

        # ── Render setup (match the rest of the deck) ─────────────────────────
        art_theme = source_data.get("theme", "")
        sym_path  = state.RENDER_DIR / source_job_id / "set_symbol.png"
        sym       = _PIL.open(sym_path) if sym_path.exists() else None
        _setup_deck_pips(source_job_id, bool(source_data.get("custom_pips", False)),
                         art_theme, source_data.get("emblem_prompt", ""))
        card_renderer.set_frame_style(source_data.get("frame_style", "builtin"))
        deck_slug = source_data.get("deck_slug") or ""
        border    = source_data.get("border_theme", "")
        videos_out = state.RENDER_DIR / source_job_id / "videos"
        videos_out.mkdir(parents=True, exist_ok=True)
        anim_src = state.RENDER_DIR / source_job_id / "_anim_src"
        anim_src.mkdir(parents=True, exist_ok=True)
        # Per-deck store of CURRENT raw art crops, written by regen (keyed by
        # render_key). When a card was rebuilt this holds its newest crop; the
        # original build crop in generated_art/<deck_slug>/ is stale for it.
        cur_art_dir = state.RENDER_DIR / source_job_id / "art"

        def _current_art_src(render_key, art_safe, cd):
            """Raw art crop for the card's CURRENTLY displayed version, for the I2V
            motion model. Prefers a regen-stashed crop (keyed by render_key), then
            the original build crop, then a Scryfall download."""
            regen_crop = cur_art_dir / f"{render_key}.png"
            if regen_crop.exists():
                return regen_crop
            build_crop = state.ART_DIR / deck_slug / f"{art_safe}.png"
            if build_crop.exists():
                return build_crop
            return _download_art_to(cd.get("scryfall_img") or "", anim_src / f"{render_key}.png")

        cancel_event = _jobs[job_id].get("cancel_event") or threading.Event()
        total = len(targets)
        start = time.time()
        meta_updates: dict[str, dict] = {}

        _effect_label = {"motion": method or "motion", "foil": f"{req.foil_style} foil",
                         "motion_foil": f"{method or 'motion'} + {req.foil_style} foil"}.get(req.effect, req.effect)
        _push(job_id, "progress", json.dumps({
            "step": "video",
            "msg":  f"Animating {total} card{'' if total == 1 else 's'} "
                    f"({_effect_label} → {fmt.upper()})…"}))

        def _base_card_image(render_key, art_safe, card_dict, themed, cd):
            """The composited still card to foil over: prefer the deck's rendered
            PNG; else render one static frame from the card's art."""
            png = state.RENDER_DIR / source_job_id / "cards" / f"{render_key}.png"
            if png.exists():
                im = _PIL.open(png); im.load(); return im.convert("RGBA")
            s = _current_art_src(render_key, art_safe, cd)
            if not s or not _Path(s).exists():
                return None
            art = _PIL.open(s).convert("RGBA")
            fr = card_renderer.render_card_frames(
                card_dict, themed, card_dict.get("oracle_text", ""), [art],
                set_symbol=sym, flavor_text=cd.get("flavor_text", ""), border_theme=border)
            return fr[0] if fr else None

        # Only the I2V motion path needs the global GPU lock; foil is CPU-only.
        import contextlib
        lock_cm = _art_lock if do_motion else contextlib.nullcontext()
        with lock_cm:
            for i, cd in enumerate(targets, 1):
                if cancel_event.is_set():
                    break
                art_safe   = _safe(cd["original_name"])
                render_key = cd.get("render_key") or art_safe
                themed     = cd.get("themed_name") or cd["original_name"]

                wall = time.time() - start
                _push(job_id, "progress", json.dumps({
                    "step": "video", "msg": f"[{i}/{total}] {themed}",
                    "card_num": i, "total": total, "card_name": themed,
                    "pct": round(i / total * 100, 1), "elapsed": round(wall),
                    "eta": round(wall / i * (total - i)) if i > 1 else 0}))

                def _cb(msg, _i=i):
                    _push(job_id, "progress", json.dumps({
                        "step": "video", "msg": f"[{_i}/{total}] {msg}",
                        "card_num": _i, "total": total}))

                try:
                    card_dict = _stored_card_to_dict(cd)
                    card_frames = None

                    if do_motion:
                        # Source art: the CURRENTLY displayed version — a regen-stashed
                        # crop if the card was rebuilt, else the original build crop,
                        # else Scryfall art.
                        src = _current_art_src(render_key, art_safe, cd)
                        if not src or not _Path(src).exists():
                            _push(job_id, "progress", json.dumps({
                                "step": "video", "msg": f"⚠ No art for {themed} — skipping"}))
                            continue
                        motion = card_video.build_motion_prompt(
                            req.motion_preset, cd.get("art_prompt", ""), custom=req.motion_prompt or "")
                        art_frames = card_video.animate(
                            _Path(src), motion, method=method,
                            frames=eff_frames, fps=eff_fps, motion_strength=motion_strength,
                            seed=(int(start) + i) % (2 ** 31), progress_cb=_cb)
                        card_frames = card_renderer.render_card_frames(
                            card_dict, themed, card_dict.get("oracle_text", ""),
                            art_frames, set_symbol=sym,
                            flavor_text=cd.get("flavor_text", ""), border_theme=border)

                    # Foil overlay (whole-card). Foil frames are already periodic,
                    # so they're encoded with loop_style="off" (the looping for the
                    # underlying motion is baked in by make_loop below).
                    if do_foil:
                        if do_motion and card_frames:
                            seq = card_video.make_loop(card_frames, eff_loop_style)
                            final = card_video.foil_frames(seq, count=len(seq),
                                                           style=req.foil_style, intensity=foil_intensity)
                        else:
                            base = _base_card_image(render_key, art_safe, card_dict, themed, cd)
                            if base is None:
                                _push(job_id, "progress", json.dumps({
                                    "step": "video", "msg": f"⚠ No card image for {themed} — skipping"}))
                                continue
                            # Foil-only loop length: requested frame count, else the
                            # default foil clip length × fps.
                            foil_count = eff_frames or card_video.frames_for_duration(
                                None, card_video._FOIL_DEFAULT_S, eff_fps, foil=True)
                            final = card_video.foil_frames(
                                [base], count=foil_count, style=req.foil_style, intensity=foil_intensity)
                        enc_loop_style = "off"   # foil sequence already loops
                    else:
                        final = card_frames
                        enc_loop_style = eff_loop_style

                    fps = eff_fps
                    out = videos_out / f"{render_key}.{fmt}"
                    card_video.encode_loop(final, out, fmt=fmt, fps=fps, loop_style=enc_loop_style)
                    # Drop any stale animation for this card in a DIFFERENT format —
                    # only AFTER the new one encodes successfully, so a failed/slow
                    # re-encode never destroys the card's existing video.
                    for _old in card_video.VIDEO_FORMATS:
                        if _old != fmt:
                            _stale = videos_out / f"{render_key}.{_old}"
                            if _stale.exists():
                                try: _stale.unlink()
                                except OSError: pass
                    meta_updates[render_key] = {
                        "method": method, "effect": req.effect, "format": fmt,
                        "foil_style": req.foil_style if do_foil else None,
                        "foil_intensity": round(foil_intensity, 2) if do_foil else None,
                        "motion": req.motion_preset if do_motion else None,
                        "motion_prompt": (req.motion_prompt or None) if do_motion else None,
                        "motion_strength": round(motion_strength, 2) if do_motion else None,
                        "loop_style": enc_loop_style,
                        "frames": len(final), "fps": fps, "loop": bool(req.loop),
                        "duration_s": round(len(final) / max(1, fps), 2),
                        "created_at": time.time()}
                    _push(job_id, "video_ready", json.dumps({
                        "key": render_key, "name": themed, "format": fmt,
                        "source_job_id": source_job_id}))
                except Exception as _ve:
                    print(f"  [animate] failed for {themed}: {_ve}")
                    _push(job_id, "progress", json.dumps({
                        "step": "video", "msg": f"⚠ {themed}: {_ve}"}))

        if cancel_event.is_set():
            _jobs[job_id]["status"] = "cancelled"
            _push(job_id, "done", json.dumps({"job_id": job_id, "cancelled": True}))
            return

        # ── Persist has_video / video_meta ────────────────────────────────────
        if meta_updates:
            updated = dict(source_data)

            def _patch(cd):
                rk = cd.get("render_key") or _safe(cd["original_name"])
                m = meta_updates.get(rk)
                return {**cd, "has_video": True, "video_meta": m} if m else cd

            updated["commander"] = _patch(updated["commander"])
            updated["deck"]      = [_patch(c) for c in updated["deck"]]
            source_json_path.write_text(json.dumps(updated), encoding="utf-8")
            if source_job_id in _jobs and isinstance(_jobs[source_job_id].get("deck"), list):
                _jobs[source_job_id]["commander"] = updated["commander"]
                _jobs[source_job_id]["deck"]      = updated["deck"]

        _jobs[job_id]["status"] = "done"
        _push(job_id, "done", json.dumps({
            "job_id": job_id, "source_job_id": source_job_id,
            "animated": len(meta_updates)}))

    except Exception as e:
        _mark_job_error(job_id, e)
    finally:
        try:
            _deck_lock.release()
        except RuntimeError:
            pass
        _finalize_job(job_id)
