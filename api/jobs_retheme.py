"""Retheme worker: re-theme a deck (new names/prompts) and generate new art.
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
    _is_single_card,
    _llm_label,
    _load_source_deck,
    _make_art_progress_cb,
    _preserve_decklist,
    _replace_card_self_ref,
    _safe_name,
    _setup_deck_pips,
    _stored_card_to_raw,
    _themed_card_to_dict,
    _write_cancelled_deck,
)
from api.models import (
    RethemeRequest,
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
from themer import ThemedCard, Themer, ThemingCancelled

# ── Retheme: re-kick the FULL generation (new theming AND new art) ───────────

def _run_retheme(job_id: str, source_job_id: str, req: RethemeRequest):
    """
    Full re-generation of an already-built deck on the SAME card list: re-run
    Ollama theming (new names/prompts) AND regenerate all card art. (Rebuild, by
    contrast, keeps the existing prompts and only re-rolls the art.)

    Flow:
      1. Load source deck.json — recovers commander/deck card data + theme params.
      2. Re-run themer.theme_deck() with the same (or overridden) theme string.
      3. Generate NEW art from the new prompts (falls back to the source deck's
         art only if ComfyUI is unavailable, so it always renders).
      4. Render every card frame with the new names + new art.
      5. Write a new deck.json under job_id so the original deck is preserved.

    The new job lives in RENDER_DIR/{job_id}/.  The client navigates to it just
    like a fresh build result.
    """
    import shutil as _shutil

    try:
        _jobs[job_id]["status"] = "building"
        # Bound up-front so retheme theming is cancellable (parity with _run_build).
        cancel_event = _jobs[job_id].get("cancel_event") or threading.Event()

        # ── Load source deck ──────────────────────────────────────────────────
        source_data = _load_source_deck(source_job_id)

        art_theme        = req.art_theme        or source_data.get("theme", "")
        commander_prompt = req.commander_prompt or source_data.get("commander_prompt", "")
        user_name_rt     = req.user_name        or source_data.get("user_name", "")
        llm_model_rt     = req.llm_model        or source_data.get("llm_model")
        face_gender_rt   = source_data.get("face_gender", "either")
        # A deck saved straight from an import has art_style="" — fall through to the
        # default rather than handing an empty key to the preset lookup.
        art_style        = (req.art_style or source_data.get("art_style") or "mtg_fantasy")
        model_speed      = (req.model_speed or source_data.get("model_speed") or "quality")
        source_deck_slug = source_data.get("deck_slug", "")
        # Whether THIS run should produce art. An un-arted import (generate_art=False)
        # can now opt in from the request; everything else inherits the source deck.
        generate_art_rt  = (req.generate_art if req.generate_art is not None
                            else bool(source_data.get("generate_art", False)))

        _push(job_id, "progress", json.dumps({
            "step": "deck",
            "msg":  f"Re-theming deck with {_llm_label()}: '{art_theme}'...",
        }))

        # ── Reconstruct raw card dicts for themer ─────────────────────────────
        # We feed the *original* MTG names and printed type lines back to the themer
        # so it re-invents names (and re-derives the tribe reskin) from scratch
        # rather than theming an already-themed card — see _stored_card_to_raw.
        raw_commander = _stored_card_to_raw(source_data["commander"])
        raw_deck      = [_stored_card_to_raw(c) for c in source_data["deck"]]

        # ── Free ComfyUI VRAM before Ollama runs ──────────────────────────────
        if _art_lock.locked():
            _push(job_id, "progress", json.dumps({
                "step": "theme",
                "msg":  "⏳ Waiting for GPU — art gen in progress…",
            }))
            with _art_lock:
                pass
        # Free ComfyUI FLUX before Ollama loads for retheme — poll for confirmation.
        _push(job_id, "progress", json.dumps({"step": "theme", "msg": f"Freeing GPU for {_llm_label()}…"}))
        _wait_for_comfyui_unload(job_id)

        # ── Re-run Ollama theming ─────────────────────────────────────────────
        _push(job_id, "progress", json.dumps({
            "step": "theme",
            "msg":  f"Theming cards with {_llm_label()} ({llm_model_rt or 'default'})…",
        }))
        themed_cmd: Optional[ThemedCard]       = None
        themed_deck: Optional[list[ThemedCard]] = None
        themer = None   # bound up-front — see the same note in _run_build
        try:
            # Themer init automatically detects model fallback if needed (qwen3:14b → qwen3:32b)
            themer = Themer(model=llm_model_rt) if llm_model_rt else Themer()

            def _theme_cb(batch_num, total_batches, cards_done, total_cards):
                pct = round(cards_done / total_cards * 100) if total_cards else 0
                _push(job_id, "progress", json.dumps({
                    "step": "theme", "msg": f"Batch {batch_num}/{total_batches} — {cards_done}/{total_cards} cards themed",
                    "batch": batch_num, "total_batches": total_batches,
                    "cards_done": cards_done, "total_cards": total_cards, "pct": pct,
                }))

            from image_gen import get_all_presets as _gap2
            _all_p2 = _gap2()
            _style_meta = _all_p2.get(art_style, _all_p2.get("mtg_fantasy", next(iter(_all_p2.values()))))

            if _is_single_card(source_data) and source_data.get("theme_mode") != "full":
                # A custom card the USER authored. `theme_deck` would rename it and
                # rewrite its flavor — which is exactly what the result screen's only
                # "give this card art" button called, so asking for art silently
                # replaced the card you designed. Author mode re-writes the art
                # prompt ONLY; the name, rules text and flavor stay verbatim.
                themed_cmd = themer.theme_single_card(
                    raw_commander, art_theme,
                    commander_prompt=commander_prompt,
                    style_guide_hint=_style_meta["style_guide_hint"],
                    themer_medium=_style_meta["themer_medium"],
                    themer_quality=_style_meta["themer_quality"],
                    lora_vocabulary=_style_meta.get("themer_vocabulary", ""),
                    ro_mode=(art_style in ("ragnarok_online", "ragnarok_sprite")),
                    theme_spec=(getattr(req, "theme_spec", None) or source_data.get("theme_spec") or None),
                    creativity=(getattr(req, "creativity", None) or source_data.get("creativity") or "balanced"),
                    gender=face_gender_rt,
                    want_flavor=not source_data.get("user_flavor"),
                )
                if source_data.get("user_flavor"):
                    themed_cmd.flavor_text = source_data["user_flavor"]
                themed_deck = []
                _push(job_id, "progress", json.dumps({
                    "step": "theme", "msg": "New art direction written", "pct": 100}))
            else:
                themed_cmd, themed_deck = themer.theme_deck(
                    art_theme, raw_commander, raw_deck,
                    commander_prompt=commander_prompt,
                    progress_callback=_theme_cb,
                    style_guide_hint=_style_meta["style_guide_hint"],
                    themer_medium=_style_meta["themer_medium"],
                    themer_quality=_style_meta["themer_quality"],
                    commander_gender=face_gender_rt,
                    lora_vocabulary=_style_meta.get("themer_vocabulary", ""),
                    commander_tribe=(getattr(req, "commander_tribe", "") or source_data.get("commander_tribe", "")),
                    tribal_map_override=source_data.get("tribal_overrides") or None,
                    # Reuse the baked map (passed above) so the reskin stays identical to
                    # the source art; only auto-generate if the flag was on but no map was
                    # ever persisted (avoids a wasted re-roll that could drift the mapping).
                    auto_theme_tribes=(bool(source_data.get("auto_theme_tribes", True))
                                       and not source_data.get("tribal_overrides")),
                    ro_mode=(art_style in ("ragnarok_online", "ragnarok_sprite")),
                    theme_spec=(getattr(req, "theme_spec", None) or source_data.get("theme_spec") or None),
                    creativity=(getattr(req, "creativity", None) or source_data.get("creativity") or "balanced"),
                    cancel_event=cancel_event,
                )
                _push(job_id, "progress", json.dumps({"step": "theme", "msg": "Theming complete", "pct": 100}))
        except ThemingCancelled:
            cancel_event.set()   # honored just below; skip plain-name fallback + art
        except Exception as e:
            # A cancel that evicted the LLM mid-request can surface as a connection
            # error — don't show a "theming failed" toast for an intentional cancel.
            if cancel_event.is_set():
                print(f"  [theme] retheme theming interrupted by cancel: {e}")
            else:
                print(f"  [theme] OLLAMA THEMING ERROR (retheme): {e}")
                traceback.print_exc()
                _push(job_id, "progress", json.dumps({
                    "step": "theme",
                    "msg": f"[!] {_llm_label()} theming failed — falling back to plain card names. Error: {e}",
                    "warning": True,
                }))
            # Don't raise — fall back to plain names like in _run_build
            themed_cmd = None
            themed_deck = None

        # Early-exit on cancel during theming — no new art yet. Write a minimal
        # cancelled deck.json (un-themed names if theming was interrupted) so the
        # new job's result view renders instead of crashing. The SOURCE deck is
        # untouched.
        if cancel_event.is_set():
            _c_cmd  = themed_cmd  if themed_cmd  is not None else ThemedCard(raw_commander["name"], raw_commander["name"], "", "", raw_commander)
            _c_deck = themed_deck if themed_deck is not None else [ThemedCard(c["name"], c["name"], "", "", c) for c in raw_deck]
            _write_cancelled_deck(job_id, _c_cmd, _c_deck, source_data.get("stats", {}),
                                  art_theme, source_data.get("generate_art", False))
            return

        # Fallback to plain card names if theming failed.
        # raw_* dicts come from _stored_card_to_dict, whose key is "name" — NOT
        # "original_name". Reading the wrong key raised KeyError here, so a themer
        # hiccup (llama-swap down mid-retheme) blew up the whole retheme instead of
        # degrading to plain names, which is how a retheme could end up mangling the
        # deck. Accept either shape.
        if themed_cmd is None or themed_deck is None:
            def _plain(c):
                n = c.get("original_name") or c.get("name") or ""
                return ThemedCard(n, n, "", "", c)
            themed_cmd  = _plain(raw_commander)
            themed_deck = [_plain(c) for c in raw_deck]

        # SAFETY NET: a retheme re-invents names/art — it must NEVER change WHICH
        # cards are in the deck. Shared with _run_build.
        themed_deck = _preserve_decklist(themed_deck, raw_deck)

        # ── Apply the player's chosen name to the commander ───────────────────
        # '<YourName>, <generated title fitting the creature-type theme>' — keeps a
        # genuinely new themed title, regenerates one when the original leaked.
        if user_name_rt and themed_cmd:
            from themer import compose_commander_name as _compose_cmd_name
            themed_cmd.themed_name = _compose_cmd_name(
                user_name_rt, themed_cmd.themed_name, raw_commander,
                theme=art_theme, world_bible=getattr(themer, "_world_bible", {}),
                tribal_map=getattr(themer, "_effective_tribal_map", {}),
                model=getattr(themer, "model", None))

        # ── Set symbol: reuse from source ─────────────────────────────────────
        render_out = state.RENDER_DIR / job_id / "cards"
        render_out.mkdir(parents=True, exist_ok=True)
        sym_path = state.RENDER_DIR / job_id / "set_symbol.png"

        old_sym = state.RENDER_DIR / source_job_id / "set_symbol.png"
        if old_sym.exists():
            _shutil.copy2(old_sym, sym_path)
            from PIL import Image as _PIL
            sym = _PIL.open(sym_path)
        else:
            sym = generate_set_symbol(art_theme, emblem_prompt=source_data.get("emblem_prompt", ""))
            sym.save(sym_path)

        # Reuse the source deck's custom pips (render_deck_thumbnails picks up the
        # module-global override set here).
        _retheme_pips = bool(source_data.get("custom_pips", False))
        _setup_deck_pips(job_id, _retheme_pips, art_theme,
                         source_data.get("emblem_prompt", ""), source_job_id)
        card_renderer.set_frame_style(source_data.get("frame_style", "builtin"))

        # Live preview: render each card the moment its art finishes and push a
        # card_ready SSE event, so retheme streams cards into the UI exactly like a
        # fresh build (previously the grid stayed empty until the whole batch was
        # done). render_deck_thumbnails below skips any card already written here
        # (it checks out.exists()), so there's no double render.
        _render_keys_rt = _build_render_keys(themed_cmd, themed_deck)

        def _retheme_card_done_cb(tc, art_path):
            name = tc.original_name
            render_key = _render_keys_rt.get(name, _safe_name(name))
            out_path = render_out / f"{render_key}.png"
            if not out_path.exists():
                try:
                    art_img = _PIL.open(art_path) if art_path and Path(art_path).exists() else None
                    processed_oracle = _replace_card_self_ref(
                        tc.card.get("oracle_text", ""), tc.original_name, tc.themed_name)
                    card_img = render_card(
                        tc.card, tc.themed_name, processed_oracle,
                        art_image=art_img, set_symbol=sym,
                        flavor_text=tc.flavor_text or "",
                        border_theme=source_data.get("border_theme", ""),
                    )
                    card_img.save(out_path, "PNG")
                except Exception as _re:
                    print(f"  [retheme render-inline] {name}: {_re}")
            if out_path.exists():
                _push(job_id, "card_ready", json.dumps({
                    "key":  render_key,
                    "name": tc.themed_name,
                }))

        # ── Generate NEW art from the re-themed prompts ───────────────────────
        # Retheme = full re-generation. Generate fresh art into a new slug; only
        # fall back to the source deck's art if ComfyUI is down, so it always renders.
        _cmd_name = (raw_commander.get("name")
                     or source_data.get("commander", {}).get("original_name", "deck"))
        new_deck_slug = (
            "".join(c if c.isalnum() else "_" for c in _cmd_name)[:20]
            + "_retheme_" + job_id[:8]
        )

        def _reuse_source_art() -> dict:
            paths: dict[str, Optional[Path]] = {}
            if source_deck_slug:
                adir = state.ART_DIR / source_deck_slug
                for tc in [themed_cmd] + themed_deck:
                    safe = "".join(ch if ch.isalnum() else "_" for ch in tc.original_name)[:48]
                    p = adir / f"{safe}.png"
                    if p.exists():
                        paths[tc.original_name] = p
            return paths

        art_paths: dict[str, Optional[Path]] = {}
        effective_slug = source_deck_slug   # what deck.json records (where art lives)

        if not generate_art_rt:
            art_paths = {}   # source was text-only (Scryfall art) — keep it that way
        else:
            _ensure_comfyui_ready(job_id)
            _health = ImageGen.health_check()
            _src_ckpt = req.checkpoint or source_data.get("checkpoint") or None
            if not _health["ok"]:
                art_paths = _reuse_source_art()
                _push(job_id, "progress", json.dumps({
                    "step": "art", "warning": True,
                    "msg": f"⚠ ComfyUI unavailable ({_health['message']}) — reused {sum(1 for v in art_paths.values() if v)} existing art image(s). Start ComfyUI and retheme again for fresh art.",
                }))
            else:
                from image_gen import _is_flux as _isflux
                from themer import OLLAMA_MODEL as _DEF_OLLAMA
                _ev = llm_model_rt or _DEF_OLLAMA
                if _src_ckpt and not _isflux(_src_ckpt):
                    _push(job_id, "progress", json.dumps({"step": "art", "msg": "Unloading previous ComfyUI models for VRAM headroom…"}))
                    _wait_for_comfyui_unload(job_id)
                _push(job_id, "progress", json.dumps({"step": "art", "msg": f"Evicting {_llm_label()} ({_ev}) from VRAM…"}))
                _wait_for_ollama_evict(_ev, job_id)
                # cancel_event already bound at the top of _run_retheme.
                _push(job_id, "progress", json.dumps({"step": "art", "msg": "Waiting for GPU…"}))
                with _art_lock:
                    try:
                        gen = ImageGen(model_speed=model_speed, art_style=art_style,
                                       checkpoint=_src_ckpt,
                                       gen_settings=_resolve_gen_settings_reusing(
                                           req.gen_settings, source_data),
                                       frame_style=source_data.get("frame_style", "builtin"))
                    except Exception as _ge:
                        gen = None
                        _push(job_id, "progress", json.dumps({"step": "art", "warning": True, "msg": f"⚠ ImageGen init failed: {_ge}"}))
                    if gen is not None and gen.available:
                        _fk = source_data.get("face_key", "")
                        _ck = source_data.get("crew_key", "")
                        _fp = [p for p in (get_face_paths(_fk) if _fk else []) if p.exists()]
                        _cp = [p for p in (get_face_paths(_ck) if _ck else []) if p.exists()]
                        _push(job_id, "progress", json.dumps({"step": "art", "msg": "Generating new card art (ComfyUI)…"}))
                        try:
                            art_paths = gen.generate_deck(
                                themed_cmd, themed_deck, new_deck_slug,
                                face_paths=_fp or None, crew_paths=_cp or None,
                                face_gender=source_data.get("face_gender", "either"),
                                crew_gender=source_data.get("crew_gender", "either"),
                                crew_prompt=source_data.get("crew_prompt", "") or "",
                                progress_callback=_make_art_progress_cb(job_id, time.time()),
                                theme_str=art_theme, cancel_event=cancel_event,
                                card_done_callback=_retheme_card_done_cb,
                                # Who gets a face is part of the DECK, not the run.
                                # Omitting these defaulted to (True, None), which
                                # stamped the commander portrait onto a non-Commander
                                # import's auto-elected display card and reverted
                                # explicit per-card assignments to crew round-robin.
                                is_commander_deck=bool(
                                    source_data.get("is_commander_deck", True)),
                                face_assignments=(
                                    source_data.get("face_assignments") or None),
                            )
                            effective_slug = new_deck_slug
                        except Exception as _ge_err:
                            traceback.print_exc()
                            art_paths = _reuse_source_art()
                            _push(job_id, "progress", json.dumps({"step": "art", "warning": True, "msg": f"⚠ Art generation failed ({_ge_err}) — reused existing art."}))
                    else:
                        art_paths = _reuse_source_art()
            # Per-card fallback: patch any card that failed gen with source art.
            if effective_slug == new_deck_slug:
                _src_fallback = None
                for _k, _v in list(art_paths.items()):
                    if _v is None:
                        if _src_fallback is None:
                            _src_fallback = _reuse_source_art()
                        if _k in _src_fallback:
                            art_paths[_k] = _src_fallback[_k]

        # Cancel during art gen: generate_deck returns early with partial art, so
        # stop before rendering/finalizing rather than emitting a half-rethemed
        # "done" deck. Persist the themed card list (cancelled) so the result view
        # shows whatever rendered, with Scryfall art for the rest. Source untouched.
        if cancel_event.is_set():
            _write_cancelled_deck(job_id, themed_cmd, list(themed_deck),
                                  source_data.get("stats", {}), art_theme,
                                  source_data.get("generate_art", False))
            return

        art_found = sum(1 for v in art_paths.values() if v)
        _push(job_id, "progress", json.dumps({
            "step": "render",
            "msg":  f"Rendering {art_found} card frame(s) with new art…",
        }))

        # ── Early checkpoint ──────────────────────────────────────────────────
        deck_json_path = state.RENDER_DIR / job_id / "deck.json"
        stats          = source_data.get("stats", {})
        checkpoint = {
            "status":           "rendering",
            "commander":        _themed_card_to_dict(themed_cmd, deck_index=0),
            "deck":             [_themed_card_to_dict(tc, deck_index=i) for i, tc in enumerate(themed_deck, 1)],
            "stats":            stats,
            "theme":            art_theme,
            "theme_spec":       source_data.get("theme_spec", {}),
            "creativity":       (getattr(req, "creativity", None) or source_data.get("creativity", "balanced")),
            "commander_prompt": commander_prompt,
            "emblem_prompt":    source_data.get("emblem_prompt", ""),
            "playstyle":        source_data.get("playstyle", ""),
            "collection":       source_data.get("collection"),  # C4 badge survives retheme
            "bracket":          source_data.get("bracket", 3),
            "bracket_label":    source_data.get("bracket_label", ""),
            "art_style":        art_style,
            "model_speed":      model_speed,
            "checkpoint":       (req.checkpoint or source_data.get("checkpoint") or ""),
            # Preserve the source deck's advanced gen settings (incl. style_variant)
            # so the rethemed deck keeps the same flavor on future regens.
            "gen_settings":     (_gen_settings_to_dict(req.gen_settings)
                                 or source_data.get("gen_settings", {})),
            "generate_art":     generate_art_rt,
            "deck_slug":        effective_slug,
            "face_key":         source_data.get("face_key", ""),
            "face_gender":      source_data.get("face_gender", "either"),
            "crew_key":         source_data.get("crew_key", ""),
            "crew_gender":      source_data.get("crew_gender", "either"),
            "user_name":        user_name_rt,
            "llm_model":        llm_model_rt or "",
            "border_theme":     source_data.get("border_theme", ""),
            "frame_style":      source_data.get("frame_style", "builtin"),
            "commander_tribe":  source_data.get("commander_tribe", ""),
            "tribal_overrides": getattr(themer, "_effective_tribal_map", None) or source_data.get("tribal_overrides", {}),
            # Carry the user's explicit picks forward so a later Edit restores them.
            "user_tribal_overrides": source_data.get("user_tribal_overrides", {}),
            "auto_theme_tribes": bool(source_data.get("auto_theme_tribes", True)),
            "world_bible":      getattr(themer, "_world_bible", {}) or source_data.get("world_bible", {}) or {},
            "custom_pips":      _retheme_pips,
            "rethemed_from":    source_job_id,
            "built_at":         time.time(),
        }
        # Identity travels with the deck across the new-job boundary (see
        # _carry_provenance) — without it a rethemed import stops reading as
        # imported, and the next Edit & Rebuild regenerates a different decklist.
        _carry_provenance(checkpoint, source_data, generated_art=bool(art_found))
        deck_json_path.write_text(json.dumps(checkpoint), encoding="utf-8")

        # ── Re-render card frames ─────────────────────────────────────────────
        _all_tcs_rt = [themed_cmd] + list(themed_deck)
        _oracle_ov_rt = {
            tc.original_name: _replace_card_self_ref(
                tc.card.get("oracle_text", ""), tc.original_name, tc.themed_name
            ) for tc in _all_tcs_rt
        }
        _flavor_ov_rt = {tc.original_name: tc.flavor_text or "" for tc in _all_tcs_rt}
        # _render_keys_rt computed earlier (before art gen) so the live-preview
        # callback and this final pass share the exact same filenames.
        saved_imgs = render_deck_thumbnails(
            themed_cmd, themed_deck, art_theme, art_paths, render_out,
            oracle_overrides=_oracle_ov_rt,
            flavor_overrides=_flavor_ov_rt,
            border_theme=source_data.get("border_theme", ""),
            render_keys=_render_keys_rt,
        )
        _push(job_id, "progress", json.dumps({
            "step": "render",
            "msg":  f"Rendered {len(saved_imgs)} card frames",
        }))

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
