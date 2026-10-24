"""Build workers: a full deck build (`_run_build`) and a single custom card (`_run_card_build`).
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

import card_renderer
import deck_import
from api import state
from api.cards import (
    _build_render_keys,
    _llm_label,
    _load_source_deck,
    _make_art_progress_cb,
    _preserve_decklist,
    _replace_card_self_ref,
    _resolve_card_source,
    _resolve_partners,
    _safe_name,
    _setup_deck_pips,
    _single_card_to_internal,
    _stored_card_to_raw,
    _themed_card_to_dict,
    _write_cancelled_deck,
)
from api.models import (
    BuildRequest,
    CardBuildRequest,
    _gen_settings_to_dict,
    _resolve_gen_settings,
)
from api.state import _art_lock, _finalize_job, _jobs, _mark_job_error, _push, _scryfall
from bracket import BRACKET_LABELS
from card_renderer import render_card, render_deck_thumbnails
from collection import load_owned_names, owned_count
from commander_analysis import build_commander_profile
from deck_builder import (
    SOURCE_COLLECTION,
    SOURCE_SCRYFALL,
    DeckBuilder,
    aggregate_duplicates,
    compute_stats,
)
from face_ref import get_face_paths
from image_gen import ImageGen
from playstyle import PLAYSTYLES, get_slot_adjustments, resolve_themes
from services import (
    _ensure_comfyui_ready,
    _wait_for_comfyui_unload,
    _wait_for_ollama_evict,
)
from set_symbol import generate_set_symbol
from themer import ThemedCard, Themer, ThemingCancelled

# ── Background deck build ─────────────────────────────────────────────────────

def _run_build(job_id: str, req: BuildRequest):
    try:
        _jobs[job_id]["status"] = "building"

        ps_label    = PLAYSTYLES.get(req.playstyle, PLAYSTYLES["auto"])["label"]
        import_meta: dict = {}
        collection_stats: Optional[dict] = None  # C4: set in the generate branch when on
        partners: list[dict] = []   # the rest of the command zone, if any (see compute_stats)

        if req.source_deck_id:
            # ── Edit & Rebuild: re-theme a saved deck's EXACT card list ───────
            # An imported deck's identity IS its card list, and the wizard offers
            # no way to change it — only the theme/art. Restoring the stored list
            # verbatim is the only option that can't drift: re-importing would pick
            # up an upstream edit, and falling through to the generate branch (what
            # used to happen, because the import source wasn't restored) silently
            # replaced the user's deck with a fresh DeckBuilder pile.
            _push(job_id, "progress", json.dumps(
                {"step": "commander", "msg": "Loading the saved decklist…"}))
            src = _load_source_deck(req.source_deck_id)
            card = _stored_card_to_raw(src["commander"])
            deck = [_stored_card_to_raw(c) for c in src.get("deck") or []]
            override = (req.commander_name or "").strip()
            if override and override.lower() not in (card.get("name", "") or "").lower():
                ov = _scryfall.get_card_by_name(override, fuzzy=True)
                if ov:
                    card = ov
            partners = [c for n in (src.get("partners") or [])
                        if (c := _scryfall.get_card_by_name(n, fuzzy=True))]
            stats = compute_stats(card, deck, partners=partners)
            if src.get("imported"):
                import_meta = {
                    "source":       src.get("import_source", ""),
                    "source_name":  src.get("import_name", ""),
                    "source_input": src.get("import_source_input", ""),
                    "unresolved":   src.get("import_unresolved", []),
                    "auto_face":    bool(src.get("import_auto_face", False)),
                }
            _push(job_id, "progress", json.dumps({"step": "deck", "msg":
                f"Reusing the saved decklist — {stats['total_cards']} cards, "
                f"face {card['name']} (no cards changed)"}))
        elif req.prebuilt_deck:
            # ── Phase-2 build: theme/render a decklist generated in phase 1 ───
            # (POST /api/deck/generate-list). Skip DeckBuilder entirely and use
            # the exact list the user reviewed when choosing tribe replacements.
            _push(job_id, "progress", json.dumps({"step": "commander", "msg": f"Looking up {req.commander_name}..."}))
            card = _scryfall.get_card_by_name(req.commander_name, fuzzy=True)
            if not card:
                raise ValueError(f"Commander not found: {req.commander_name}")
            deck = list(req.prebuilt_deck)
            # generate-list (phase 1) already drafted against the union identity AND
            # appended the partner card(s) into this exact list (`deck.append(pc)`,
            # mirroring the import branch) — do NOT append them again here. Re-resolve
            # partners anyway so phase 2's own stats (and later the mentor/analyze
            # calls) see the SAME command-zone identity instead of falling back to the
            # lead card alone.
            partners = _resolve_partners(card, req.partner_names)
            stats = compute_stats(card, deck, partners=partners)
            _push(job_id, "progress", json.dumps({"step": "deck", "msg":
                f"Using pre-generated deck — {stats['total_cards']} cards, commander {card['name']}"}))
        elif req.deck_url or req.deck_list:
            # ── Import an existing decklist ───────────────────────────────────
            src_input = (req.deck_url or req.deck_list)
            _push(job_id, "progress", json.dumps(
                {"step": "commander", "msg": "Importing decklist…"}))
            try:
                imported = deck_import.import_deck(src_input, _scryfall)
            except deck_import.DeckImportError as e:
                raise ValueError(str(e))
            card = imported.commander
            # An explicitly typed commander/face name overrides the auto-elected
            # face (and fills in if election somehow produced nothing). Only a name
            # that actually differs from the current face triggers a Scryfall lookup.
            override = (req.commander_name or "").strip()
            if override and (card is None or override.lower() not in (card.get("name", "") or "").lower()):
                ov = _scryfall.get_card_by_name(override, fuzzy=True)
                if ov:
                    card = ov
            if not card:
                # With auto-election this is essentially unreachable (any non-empty
                # deck yields a face); kept as a guard for a truly empty import.
                raise ValueError(
                    "Couldn't read any cards from that deck. Check the URL or "
                    "decklist text and try again.")
            deck = list(imported.deck)
            partners = imported.partners
            # Partner/companion commanders aren't the face — render them as cards.
            for p in imported.partners:
                pc = dict(p); pc.setdefault("quantity", 1); deck.append(pc)
            # Partners also carry COLOUR IDENTITY. Folding them into `deck` covers
            # their pips and types; passing them through covers the identity that
            # assess_colors filters sources by.
            stats = compute_stats(card, deck, partners=imported.partners)
            face_auto = bool(imported.auto_face) and card is imported.commander
            import_meta = {"source": imported.source, "source_name": imported.name,
                           "source_input": src_input, "unresolved": imported.unresolved,
                           "auto_face": face_auto}
            _push(job_id, "progress", json.dumps({"step": "deck", "msg":
                f"Imported {imported.name} — {stats['total_cards']} cards, "
                + (f"face (auto-selected) {card['name']}" if face_auto else f"commander {card['name']}")
                + (f" ({len(imported.unresolved)} unresolved)" if imported.unresolved else "")}))
        else:
            # ── Generate a deck from a commander ──────────────────────────────
            _push(job_id, "progress", json.dumps({"step": "commander", "msg": f"Looking up {req.commander_name}..."}))
            card = _scryfall.get_card_by_name(req.commander_name, fuzzy=True)
            if not card:
                raise ValueError(f"Commander not found: {req.commander_name}")
            _push(job_id, "progress", json.dumps({"step": "commander", "msg": f"Found: {card['name']}"}))

            partners       = _resolve_partners(card, req.partner_names)
            if partners:
                _push(job_id, "progress", json.dumps({"step": "commander", "msg":
                      "Partnered with " + ", ".join(p["name"] for p in partners)}))
            profile        = build_commander_profile(card, partners)
            active_themes  = resolve_themes(req.playstyle, profile.themes)
            slot_overrides = get_slot_adjustments(req.playstyle)

            source = _resolve_card_source(req.card_source, req.use_collection)
            owned = load_owned_names() if source != SOURCE_SCRYFALL else set()
            if source != SOURCE_SCRYFALL:
                _push(job_id, "progress", json.dumps({"step": "deck", "msg": (
                    (f"Building ONLY from your collection ({len(owned)} owned cards)…"
                     if source == SOURCE_COLLECTION
                     else f"Building from your collection ({len(owned)} owned cards)…")
                    if owned else
                    "Collection is empty — building normally "
                    "(export from MythScanner to Documents/MythSuite)."
                )}))
            _push(job_id, "progress", json.dumps({"step": "deck", "msg": "Building 99-card deck..."}))
            builder = DeckBuilder(_scryfall)
            deck = builder.build(
                profile,
                theme_override  = active_themes,
                slot_overrides  = slot_overrides,
                playstyle_label = ps_label,
                bracket         = req.bracket,
                owned           = owned,
                card_source     = source,
                partner_count   = len(partners),
            )
            if builder.source_fallback:
                _push(job_id, "progress", json.dumps({"step": "deck",
                                                      "msg": builder.source_fallback}))
            if builder.shortfall:
                _push(job_id, "progress", json.dumps({"step": "deck", "msg":
                    "Collection couldn't cover: " + ", ".join(
                        f"{k} (-{v})" for k, v in sorted(builder.shortfall.items()))}))
            # Partner/companion commanders aren't the face — render them as cards, same
            # convention the import branch already uses. build()'s `partner_count`
            # already shrank the drafted library by this many, so appending them here
            # lands on exactly 100 total (library + face + partners), not 101.
            for p in partners:
                pc = dict(p); pc.setdefault("quantity", 1); deck.append(pc)
            # Collapse duplicate basics into quantity entries (theme/render once,
            # export replicates) — same model as imported decks.
            deck = aggregate_duplicates(deck)
            # partners= widens the identity assess_colors filters sources by (see
            # compute_stats' docstring) — without it a partner build's own union-identity
            # duals/fetches (Command Tower, City of Brass, ...) get their non-lead colours
            # filtered OUT of the report, so a real WBUG manabase reads as "0 U sources,
            # 0 G sources" / colors.ok:False. Found live 2026-08-25 building Tymna the
            # Weaver + Thrasios, Triton Hero — the deck actually holds an Island, 3
            # Forests and six 5-colour fixers.
            stats = compute_stats(card, deck, partners=partners)
            # Gate on the RESOLVED source, not the legacy boolean: a request carrying
            # only card_source="collection" built strictly but reported no collection
            # stats at all, so deck.json lost the block and StepDeck's owned badge
            # vanished. Keys match generate_list's block so both endpoints agree.
            if source != SOURCE_SCRYFALL:
                _spells = [card] + [c for c in deck
                                    if "basic" not in (c.get("type_line", "") or "").lower()]
                have = owned_count(_spells, owned)
                collection_stats = {
                    "source": source, "shortfall": builder.shortfall,
                    "enabled": True, "owned": have, "total": len(_spells),
                    "collection_size": len(owned),
                }
                _push(job_id, "progress", json.dumps({"step": "deck", "msg": (
                    f"You own {have} of {len(_spells)} non-basic cards in this deck"
                )}))
            _push(job_id, "progress", json.dumps({"step": "deck", "msg": f"Built {stats['total_cards']} cards"}))

        # ── Theme via Ollama ──────────────────────────────────────────────────
        art_theme = req.art_theme or f"epic fantasy art centered on {card['name']}"

        # If another build is currently generating art via ComfyUI, wait for
        # it to finish before loading the Ollama LLM.  Both FLUX (fp8) and
        # qwen3:14b need substantial VRAM; running them concurrently causes
        # GPU OOM → ComfyUI card-generation timeouts.
        if _art_lock.locked():
            _push(job_id, "progress", json.dumps({
                "step": "theme",
                "msg":  "⏳ Waiting for GPU — another deck is currently generating art…",
            }))
            with _art_lock:
                pass   # block until the lock is free, then release immediately

        # Free ComfyUI from VRAM before Ollama runs.
        # ComfyUI can hold the image model resident between builds (~11-12 GB);
        # polling /system_stats ensures VRAM is actually free before Ollama loads.
        _push(job_id, "progress", json.dumps({"step": "theme", "msg": f"Freeing GPU for {_llm_label()}…"}))
        _wait_for_comfyui_unload(job_id)

        _llm = req.llm_model or None   # None → Themer uses default qwen3:14b
        _push(job_id, "progress", json.dumps({
            "step": "theme",
            "msg":  f"Theming cards with {_llm_label()} ({_llm or 'default'})..."
        }))

        # Fetched here (not just before art) so theming itself is cancellable —
        # a cancel during the LLM batches now stops the build instead of letting
        # all ~20 batches finish first.
        cancel_event = _jobs[job_id].get("cancel_event") or threading.Event()

        themed_cmd: Optional[ThemedCard] = None
        themed_deck: Optional[list[ThemedCard]] = None
        # Bound BEFORE the try: if the Themer CONSTRUCTOR raises (llama-swap down),
        # the except below degrades to plain names, but every later
        # getattr(themer, …) hit an unbound local and killed the whole build with
        # "cannot access local variable 'themer'" — so a gateway that wasn't running
        # lost the deck instead of just its themed names.
        themer = None
        try:
            themer = Themer(model=_llm) if _llm else Themer()

            def _theme_cb(batch_num, total_batches, cards_done, total_cards):
                pct = round(cards_done / total_cards * 100) if total_cards else 0
                _push(job_id, "progress", json.dumps({
                    "step":         "theme",
                    "msg":          f"Batch {batch_num}/{total_batches} — {cards_done}/{total_cards} cards themed",
                    "batch":        batch_num,
                    "total_batches": total_batches,
                    "cards_done":   cards_done,
                    "total_cards":  total_cards,
                    "pct":          pct,
                }))

            # Fetch art-style themer vocabulary so Ollama generates prompts
            # whose medium/quality language matches the selected LoRA preset.
            from image_gen import get_all_presets as _gap
            _all_p = _gap()
            _style_meta = _all_p.get(req.art_style or "mtg_fantasy", _all_p.get("mtg_fantasy", next(iter(_all_p.values()))))

            themed_cmd, themed_deck = themer.theme_deck(
                art_theme, card, deck,
                commander_prompt=req.commander_prompt,
                progress_callback=_theme_cb,
                style_guide_hint=_style_meta["style_guide_hint"],
                themer_medium=_style_meta["themer_medium"],
                themer_quality=_style_meta["themer_quality"],
                commander_gender=req.face_gender,
                lora_vocabulary=_style_meta.get("themer_vocabulary", ""),
                commander_tribe=req.commander_tribe or "",
                tribal_map_override=req.tribal_overrides or None,
                auto_theme_tribes=bool(req.auto_theme_tribes),
                ro_mode=(req.art_style in ("ragnarok_online", "ragnarok_sprite")),
                theme_spec=req.theme_spec or None,
                creativity=req.creativity or "balanced",
                cancel_event=cancel_event,
            )
            _push(job_id, "progress", json.dumps({"step": "theme", "msg": "Theming complete",
                                                   "pct": 100}))
        except ThemingCancelled:
            # User hit cancel mid-theming — honored below; no plain-name fallback.
            cancel_event.set()
        except Exception as e:
            # A cancel that evicted the LLM mid-request can surface here as a
            # connection error — don't show a scary "theming failed" toast for it.
            if cancel_event.is_set():
                print(f"  [theme] theming interrupted by cancel: {e}")
            else:
                print(f"  [theme] OLLAMA THEMING ERROR: {e}")
                traceback.print_exc()
                _push(job_id, "progress", json.dumps({
                    "step": "theme",
                    "msg": f"[!] {_llm_label()} theming failed — falling back to plain card names. Error: {e}",
                    "warning": True,
                }))

        # ── Early-exit on cancel (during theming) ─────────────────────────────
        # The full checkpoint is written further down (after theming), so cancel
        # here would otherwise leave NO deck.json — and the result view crashes on
        # the missing card list. Write a minimal deck.json from the un-themed cards
        # (themed_cmd/_deck are None when theming was interrupted) so the page shows
        # the original deck list with Scryfall art and a cancelled status, mirroring
        # how an art-phase cancel shows its partial deck. (VRAM eviction was already
        # scheduled by the cancel endpoint; _finalize_job runs via the outer finally.)
        if cancel_event.is_set():
            _c_cmd  = themed_cmd  if themed_cmd  is not None else ThemedCard(card["name"], card["name"], "", "", card)
            _c_deck = themed_deck if themed_deck is not None else [ThemedCard(c["name"], c["name"], "", "", c) for c in deck]
            _write_cancelled_deck(job_id, _c_cmd, _c_deck, stats, art_theme, req.generate_art)
            return

        if themed_cmd is None:
            def _plain(c): return ThemedCard(c["name"], c["name"], "", "", c)
            themed_cmd  = _plain(card)
            themed_deck = [_plain(c) for c in deck]

        # SAFETY NET (parity with retheme): theming re-invents names, never the
        # card list. Backfill anything a short/partial themer batch dropped.
        themed_deck = _preserve_decklist(themed_deck, deck)

        # ── Apply the player's chosen name to the commander ───────────────────
        # Runs BEFORE the Ollama eviction below so a title regeneration (rare —
        # only when the themed title leaked the original) reuses the warm LLM
        # instead of forcing a reload right after we evict it. (Imported explicitly
        # because the local `themer` here is a Themer INSTANCE, not the module.)
        if req.user_name:
            from themer import compose_commander_name as _compose_cmd_name
            themed_cmd.themed_name = _compose_cmd_name(
                req.user_name, themed_cmd.themed_name, card,
                theme=art_theme, world_bible=getattr(themer, "_world_bible", {}),
                tribal_map=getattr(themer, "_effective_tribal_map", {}),
                model=getattr(themer, "model", None) or _llm or None)
            _push(job_id, "progress", json.dumps({
                "step": "theme",
                "msg":  f"Commander renamed: {themed_cmd.themed_name}",
            }))

        # ── Unload Ollama before proceeding to symbol / art gen ────────────────
        # Prevents Ollama from competing with ComfyUI for VRAM during art gen.
        # Do this even if theming failed — Ollama may still be partially resident.
        if req.generate_art:
            from themer import OLLAMA_MODEL as _DEFAULT_OLLAMA
            _ollama_model = _llm or _DEFAULT_OLLAMA
            _push(job_id, "progress", json.dumps({"step": "symbol", "msg": "Freeing GPU for art generation…"}))
            _wait_for_ollama_evict(_ollama_model, job_id)

        # ── Set symbol ────────────────────────────────────────────────────────
        _push(job_id, "progress", json.dumps({"step": "symbol", "msg": "Generating set symbol..."}))
        sym      = generate_set_symbol(art_theme, emblem_prompt=req.emblem_prompt or "")
        sym_path = state.RENDER_DIR / job_id / "set_symbol.png"
        sym_path.parent.mkdir(parents=True, exist_ok=True)
        sym.save(sym_path)

        # ── Custom mana pips (optional) ───────────────────────────────────────
        # Generated up front so the inline render callback (during art gen) and
        # the final render pass both pick them up. Best FLUX quality needs
        # ComfyUI up — ensure it when art is requested; falls back to a procedural
        # silhouette otherwise.
        if req.custom_pips and req.generate_art:
            _ensure_comfyui_ready(job_id)
        _pip_emblem = _setup_deck_pips(job_id, req.custom_pips, art_theme,
                                       req.emblem_prompt or "")
        card_renderer.set_frame_style(req.frame_style)
        if _pip_emblem is not None:
            # The custom-pip silhouette doubles as the deck emblem so the set
            # symbol reflects the requested subject (and matches the pips).
            sym = _pip_emblem

        # ── Early checkpoint: write deck.json NOW (before art gen + render) ──
        # Art gen is the longest step (30+ min). If the server crashes or
        # reloads during that step, the themed deck data is preserved here.
        deck_json_path = state.RENDER_DIR / job_id / "deck.json"
        deck_json_path.parent.mkdir(parents=True, exist_ok=True)
        # Compute deck_slug here so it's available for retheme later
        _deck_slug_base = ("".join(c if c.isalnum() else "_" for c in card["name"])[:28]
                           + "_" + job_id[:8])
        checkpoint = {
            "status":           "rendering",   # updated to "done" at the end
            "commander":        _themed_card_to_dict(themed_cmd, deck_index=0),
            "deck":             [_themed_card_to_dict(tc, deck_index=i) for i, tc in enumerate(themed_deck, 1)],
            "stats":            stats,
            "theme":            art_theme,
            "theme_spec":       req.theme_spec or {},
            "creativity":       req.creativity or "balanced",
            "commander_prompt": req.commander_prompt,
            "emblem_prompt":    req.emblem_prompt,
            "playstyle":        ps_label,
            "playstyle_description": PLAYSTYLES.get(req.playstyle, PLAYSTYLES.get("auto", {})).get("description", ""),
            "collection":       collection_stats,   # C4: owned-card coverage (None = off)
            "bracket":          req.bracket,
            "bracket_label":    BRACKET_LABELS.get(req.bracket, str(req.bracket)),
            "art_style":        req.art_style,
            "checkpoint":       req.checkpoint or "",
            "model_speed":      req.model_speed,
            # Persist the advanced gen settings (incl. a pinned style_variant) so
            # rebuild / regen / retheme can recover them — see _resolve_gen_settings_reusing.
            "gen_settings":     _gen_settings_to_dict(req.gen_settings),
            "generate_art":     req.generate_art,
            "deck_slug":        _deck_slug_base,
            "face_key":         req.face_key or "",
            "face_gender":      req.face_gender,
            "crew_key":         req.crew_key or "",
            "crew_gender":      req.crew_gender,
            "crew_prompt":      req.crew_prompt or "",
            "is_commander_deck": req.is_commander_deck,
            "face_assignments": req.face_assignments or {},
            "user_name":        req.user_name or "",
            "llm_model":        req.llm_model or "",
            "border_theme":     req.border_theme or "",
            "frame_style":      req.frame_style or "builtin",
            "commander_tribe":  req.commander_tribe or "",
            # Persist the EFFECTIVE tribe map (user override OR the auto-generated
            # one) so Rebuild/Retheme reuse the same replacement as the baked art.
            "tribal_overrides": getattr(themer, "_effective_tribal_map", None) or req.tribal_overrides or {},
            # Persist the user's EXPLICIT per-tribe picks separately. Edit restores
            # ONLY these (not the merged effective map) so auto-reskins regenerate
            # from the edited theme — otherwise the baked map froze every creature
            # type on Edit & Rebuild even when the theme changed.
            "user_tribal_overrides": req.tribal_overrides or {},
            "auto_theme_tribes": bool(req.auto_theme_tribes),
            # Set Bible (world + per-colour factions + lore) for display / debugging.
            "world_bible":      getattr(themer, "_world_bible", {}) or {},
            "custom_pips":      req.custom_pips,
            # The rest of the command zone, if any — a partner/background the lead card's
            # OWN name/colours don't cover. Not folded into `deck` for generated decks (the
            # 99-card slot plan has no partner-aware target size yet), so this is metadata
            # only: it lets a later mentor/analyze call see the full colour identity instead
            # of re-deriving a false "colors.ok: False" off the lead alone.
            "partners":         [p.get("name") for p in partners if p.get("name")],
            "imported":         bool(import_meta),
            "import_source":    import_meta.get("source", ""),
            "import_name":      import_meta.get("source_name", ""),
            # The exact URL / pasted text this deck came from. Persisted so the deck
            # view can name its origin and a later re-import can be offered without
            # the user digging the link back out.
            "import_source_input": import_meta.get("source_input", ""),
            "import_unresolved": import_meta.get("unresolved", []),
            "import_auto_face": import_meta.get("auto_face", False),
            "built_at":         time.time(),
        }
        deck_json_path.write_text(json.dumps(checkpoint), encoding="utf-8")

        # render_out is defined early so the inline-render callback can use it
        render_out = state.RENDER_DIR / job_id / "cards"
        render_out.mkdir(parents=True, exist_ok=True)
        # cancel_event was fetched before theming (see above) so it's already bound.

        # ── Art generation (optional) ─────────────────────────────────────────
        art_paths: dict[str, Optional[Path]] = {}
        if req.generate_art:
            # Auto-start ComfyUI if it isn't running (waits for it to load), so a
            # build doesn't silently fall back to Scryfall art just because the
            # backend was down. No-op if it's already up or can't be located.
            _ensure_comfyui_ready(job_id)
            # Pre-flight: explicitly check ComfyUI BEFORE evicting Ollama and
            # taking the GPU lock.  If ComfyUI isn't running we tell the user
            # exactly why with a clear, actionable message — and the build
            # continues with Scryfall placeholder art rather than failing.
            health = ImageGen.health_check()
            if not health["ok"]:
                _push(job_id, "progress", json.dumps({
                    "step":     "art",
                    "msg":      f"⚠ Art generation skipped — {health['message']}",
                    "warning":  True,
                    "hint":     health.get("hint", ""),
                }))
                print(f"  [art] Pre-flight failed: {health['message']}")
                if health.get("hint"):
                    print(f"        Hint: {health['hint']}")

            else:
                # Evict Ollama from VRAM and confirm via /api/ps before loading FLUX.
                from themer import OLLAMA_MODEL as _DEFAULT_OLLAMA
                _evict_model = req.llm_model or _DEFAULT_OLLAMA
                _push(job_id, "progress", json.dumps({"step": "art", "msg": f"Evicting {_llm_label()} ({_evict_model}) from VRAM…"}))
                _wait_for_ollama_evict(_evict_model, job_id)

                _push(job_id, "progress", json.dumps({"step": "art", "msg": "Waiting for GPU…"}))
                with _art_lock:   # serialize: only one build drives ComfyUI at a time
                    try:
                        gen = ImageGen(model_speed=req.model_speed, art_style=req.art_style,
                                      checkpoint=req.checkpoint,
                                      gen_settings=_resolve_gen_settings(req.gen_settings),
                                      frame_style=req.frame_style or "builtin")
                    except Exception as _ge:
                        _push(job_id, "progress", json.dumps({
                            "step": "art",
                            "msg":  f"⚠ Art generation skipped — ImageGen init failed: {_ge}",
                            "warning": True,
                        }))
                        gen = None

                    if gen is not None:
                        print(f"[DEBUG] ImageGen: checkpoint={gen.checkpoint}, available={gen.available}, "
                              f"face_method={gen.face_method}, speed={req.model_speed}")
                        # Warn in the SSE stream if the user wanted Schnell but got Dev
                        if gen.available and req.model_speed == "fast" and gen.checkpoint and "schnell" not in gen.checkpoint.lower():
                            _push(job_id, "progress", json.dumps({
                                "step":    "art",
                                "msg":     f"⚡ Schnell not found — using {gen.checkpoint} (dev quality).",
                                "warning": True,
                            }))

                    if gen is not None and gen.available:
                        # Use the pre-computed slug (same value stored in checkpoint)
                        deck_slug = _deck_slug_base

                        # Resolve commander face photos
                        face_paths: list[Path] = []
                        if req.face_key:
                            face_paths = get_face_paths(req.face_key)
                            if face_paths:
                                _push(job_id, "progress", json.dumps({
                                    "step": "art",
                                    "msg": f"Commander face: {len(face_paths)} photo(s) — {gen.face_method_label}",
                                }))
                            else:
                                _push(job_id, "progress", json.dumps({
                                    "step": "art",
                                    "msg": "Commander face key supplied but no photos found",
                                }))

                        # Resolve crew face photos (for creature cards)
                        crew_paths: list[Path] = []
                        if req.crew_key:
                            crew_paths = get_face_paths(req.crew_key)
                            if crew_paths:
                                _push(job_id, "progress", json.dumps({
                                    "step": "art",
                                    "msg": f"Crew photos: {len(crew_paths)} photo(s) — applied to humanoid creatures",
                                }))
                            else:
                                _push(job_id, "progress", json.dumps({
                                    "step": "art",
                                    "msg": "Crew key supplied but no photos found",
                                }))

                        _push(job_id, "progress", json.dumps({"step": "art", "msg": "Generating card art (ComfyUI)..."}))
                        _art_start_time = time.time()

                        _art_cb = _make_art_progress_cb(job_id, _art_start_time)

                        # Pre-compute render_keys for indexed filenames (used in card_done_cb)
                        _render_keys_inline = _build_render_keys(themed_cmd, themed_deck)

                        def _card_done_cb(tc, art_path):
                            """Render this card immediately and push a card_ready SSE event."""
                            name = tc.original_name
                            # Use indexed render_key format (CardName_000 for commander, CardName_001+ for deck)
                            render_key = _render_keys_inline.get(name, _safe_name(name))
                            out_path = render_out / f"{render_key}.png"
                            if not out_path.exists():
                                try:
                                    from PIL import Image as _PILImage
                                    art_img = _PILImage.open(art_path) if art_path and art_path.exists() else None
                                    # Use processed oracle text (self-refs replaced)
                                    processed_oracle = _replace_card_self_ref(
                                        tc.card.get("oracle_text", ""),
                                        tc.original_name, tc.themed_name,
                                    )
                                    card_img = render_card(
                                        tc.card, tc.themed_name,
                                        processed_oracle,
                                        art_image=art_img,
                                        set_symbol=sym,
                                        flavor_text=tc.flavor_text or "",
                                        border_theme=req.border_theme or "",
                                    )
                                    card_img.save(out_path, "PNG")
                                except Exception as _re:
                                    print(f"  [render-inline] {name}: {_re}")
                            if out_path.exists():
                                _push(job_id, "card_ready", json.dumps({
                                    "key":  render_key,
                                    "name": tc.themed_name,
                                }))

                        # Wrap generate_deck so transient ComfyUI errors mid-run
                        # don't abort the whole build — we still want the deck to
                        # finish with whatever art was produced + Scryfall fallback.
                        try:
                            art_paths = gen.generate_deck(
                                themed_cmd, themed_deck, deck_slug,
                                face_paths=face_paths or None,
                                crew_paths=crew_paths or None,
                                face_gender=req.face_gender,
                                crew_gender=req.crew_gender,
                                crew_prompt=req.crew_prompt,
                                progress_callback=_art_cb,
                                theme_str=art_theme,
                                card_done_callback=_card_done_cb,
                                cancel_event=cancel_event,
                                is_commander_deck=req.is_commander_deck,
                                face_assignments=(req.face_assignments or None),
                            )
                        except Exception as _ge_err:
                            _push(job_id, "progress", json.dumps({
                                "step": "art",
                                "msg":  f"⚠ Art generation aborted: {_ge_err}",
                                "warning": True,
                            }))
                            print(f"  [art] generate_deck raised: {_ge_err}")
                            traceback.print_exc()

                        # If we got zero art back from ComfyUI, surface that
                        # explicitly — the user asked for generated art and is
                        # otherwise about to be silently handed Scryfall art.
                        if not any(p for p in art_paths.values()):
                            _push(job_id, "progress", json.dumps({
                                "step":    "art",
                                "msg":     "⚠ No art was generated by ComfyUI — falling back to Scryfall card art for all cards.",
                                "warning": True,
                                "hint":    "Check ComfyUI's console for the last error (commonly: missing LoRA file or workflow validation).",
                            }))

        # ── Early-exit on cancel ──────────────────────────────────────────────
        # If the user cancelled, skip VRAM freeing AND the render step.
        # render_deck_thumbnails() opens/downloads ~100 images and writes ~100 PNGs
        # — running it on a cancelled build hammers disk I/O and system RAM.
        # More critically: if we call _wait_for_comfyui_unload() here AND the
        # background task (_free_all_vram) is also running, BOTH threads compete
        # to unload/free models, causing severe disk thrashing (paging, memory
        # pressure). Let the background task handle VRAM cleanup exclusively.
        if cancel_event.is_set():
            _jobs[job_id]["status"] = "cancelled"
            # Stamp deck.json so disk state matches — _load_deck_from_disk can
            # then return the partial deck correctly after a server restart.
            # Also backfill has_render flags so the gallery shows whatever art
            # was generated before cancellation rather than Scryfall fallbacks.
            try:
                if deck_json_path.exists():
                    _d = json.loads(deck_json_path.read_text(encoding="utf-8"))
                    _d["status"] = "cancelled"
                    # Scan cards/ dir to fix has_render for partially-rendered decks
                    _cards_dir = render_out
                    if _cards_dir.exists():
                        _rendered = {fp.stem for fp in _cards_dir.glob("*.png")}
                        if _rendered:
                            _cmd = _d.get("commander")
                            if isinstance(_cmd, dict):
                                _rk = _cmd.get("render_key", "")
                                if _rk:
                                    _cmd["has_render"] = _rk in _rendered
                            for _card in _d.get("deck") or []:
                                _rk = _card.get("render_key", "")
                                if _rk:
                                    _card["has_render"] = _rk in _rendered
                    deck_json_path.write_text(json.dumps(_d), encoding="utf-8")
                    # Keep in-memory job in sync so current session sees it too
                    _jobs[job_id].update(_d)
                    _jobs[job_id]["status"] = "cancelled"
            except Exception:
                pass
            _push(job_id, "done", json.dumps({"job_id": job_id, "cancelled": True}))
            return

        # ── Release FLUX VRAM now that art gen is done ────────────────────────
        # render_deck_thumbnails() is CPU-only (PIL).  Free FLUX so VRAM is
        # available if the user immediately triggers another build or retheme.
        # Only do this if NOT cancelled (see above).
        if req.generate_art:
            _wait_for_comfyui_unload(job_id)

        # ── Render card frames ────────────────────────────────────────────────
        # Cards already rendered inline (via _card_done_cb) are skipped automatically.
        _push(job_id, "progress", json.dumps({"step": "render", "msg": "Rendering card frames..."}))
        # Build oracle/flavor overrides so the renderer uses processed text
        _all_tcs = [themed_cmd] + list(themed_deck)
        _oracle_ov = {
            tc.original_name: _replace_card_self_ref(
                tc.card.get("oracle_text", ""), tc.original_name, tc.themed_name
            ) for tc in _all_tcs
        }
        _flavor_ov = {tc.original_name: tc.flavor_text or "" for tc in _all_tcs}
        # Recompute render_keys here (deterministic) so this works whether or not
        # the art-gen branch ran — generate_art=false skips _render_keys_inline.
        saved_imgs = render_deck_thumbnails(
            themed_cmd, themed_deck, art_theme, art_paths, render_out,
            oracle_overrides=_oracle_ov,
            flavor_overrides=_flavor_ov,
            border_theme=req.border_theme or "",
            render_keys=_build_render_keys(themed_cmd, themed_deck),
        )
        _push(job_id, "progress", json.dumps({"step": "render", "msg": f"Rendered {len(saved_imgs)} card frames"}))

        # ── Finalize result ───────────────────────────────────────────────────
        # Re-serialize with has_render flags set correctly, then overwrite checkpoint
        result = dict(checkpoint)
        result["status"]    = "done"
        result["commander"] = _themed_card_to_dict(themed_cmd, deck_index=0, has_render=themed_cmd.original_name in saved_imgs)
        result["deck"]      = [_themed_card_to_dict(tc, deck_index=i, has_render=tc.original_name in saved_imgs) for i, tc in enumerate(themed_deck, 1)]
        _jobs[job_id].update(result)

        # Overwrite checkpoint with final done state
        deck_json_path.write_text(json.dumps(result), encoding="utf-8")

        _push(job_id, "done", json.dumps({"job_id": job_id}))

    except Exception as e:
        _mark_job_error(job_id, e)
    finally:
        _finalize_job(job_id)


# ── Single custom card build ─────────────────────────────────────────────────

def _fallback_art_prompt(card: dict, theme: str, subject: str,
                         style_meta: dict, ro_mode: bool) -> str:
    """Build an art prompt from the card itself, with no LLM.

    This is what a single-card build ships when the LLM gateway is down (or the
    user turned AI prompt-writing off without typing one). The previous fallback
    was the bare theme seed — literally "epic fantasy art centered on <name>" —
    which discarded the type line, the mana colours and the subject description
    the user had already typed, so an offline build produced generic art that
    ignored the card. Everything here is deterministic.
    """
    from themer import _color_palette_hint, _extract_theme_palette

    name    = (card.get("name") or "").strip()
    tl      = (card.get("type_line") or "").lower()
    palette = _color_palette_hint(card.get("color_identity") or [],
                                  _extract_theme_palette(theme or ""))
    # What KIND of thing is this? Same distinction the themer's per-type subject
    # directives make — an Equipment must not be painted as a person.
    if "creature" in tl or "planeswalker" in tl:
        shot = "dramatic character illustration, full figure"
    elif "land" in tl:
        shot = "sweeping environment scene, no people"
    elif "artifact" in tl:
        shot = "an ornate crafted object as the sole subject, no people"
    elif "enchantment" in tl:
        shot = "a magical phenomenon suffusing the scene"
    else:
        shot = "a decisive moment of the spell taking effect"

    bits = [name, (card.get("type_line") or "").strip(), shot]
    if (subject or "").strip():
        bits.append(subject.strip())
    if (theme or "").strip():
        bits.append(theme.strip())
    bits.append(palette)
    if style_meta.get("themer_quality"):
        bits.append(style_meta["themer_quality"])
    prompt = ", ".join(b for b in bits if b)

    if ro_mode:
        from themer import apply_ro_tokens as _apply_ro
        prompt = _apply_ro(prompt, card, override_text=subject)
    return prompt


def _run_card_build(job_id: str, req: "CardBuildRequest"):
    """Build ONE user-authored custom card: theme → (optional) art → render.

    Persists a 'deck of one' (commander = the card, deck = []) so the result view
    and every job-keyed per-card action (regen / animate / 3D / export / history /
    retheme / rebuild / duplicate) work on it with no special-casing.
    """
    from PIL import Image as _PIL

    try:
        _jobs[job_id]["status"] = "building"
        card = _single_card_to_internal(req.card)
        name = card["name"]
        stats = compute_stats(card, [])
        # The USER's theme (may be empty — "just make this card" is a real answer)
        # is what gets persisted and shown. `art_theme` is the internal prompt seed
        # and falls back to a synthetic string; persisting THAT as the deck's theme
        # put a chip reading "epic fantasy art centered on Vaultkeeper Ilyra" on the
        # result screen and in History, as if the user had typed it.
        user_theme = (req.art_theme or "").strip()
        art_theme  = user_theme or f"epic fantasy art centered on {name}"
        ro_mode    = req.art_style in ("ragnarok_online", "ragnarok_sprite")

        _push(job_id, "progress", json.dumps({"step": "commander", "msg": f"Custom card: {name}"}))

        # Art-style preset → themer medium/quality/vocabulary (same mapping as builds).
        from image_gen import get_all_presets as _gap
        _all_p = _gap()
        _style_meta = _all_p.get(req.art_style or "mtg_fantasy",
                                 _all_p.get("mtg_fantasy", next(iter(_all_p.values()))))

        _llm = req.llm_model or None
        cancel_event = _jobs[job_id].get("cancel_event") or threading.Event()

        # Does this run need the LLM?
        #   - "full" theming always does (it invents the name and flavor).
        #   - Otherwise only when the AI is the one writing the art prompt, i.e.
        #     the user didn't supply one.
        # The old expression had three overlapping clauses that reduced to the same
        # thing but read as if "custom" mattered in full mode, which it didn't.
        custom_prompt = (req.art_prompt or "").strip()
        use_custom_prompt = (req.art_prompt_mode == "custom") and bool(custom_prompt)
        need_llm = (req.theme_mode == "full") or not use_custom_prompt

        tc: Optional[ThemedCard] = None
        world_bible: dict = {}
        if need_llm:
            _push(job_id, "progress", json.dumps({"step": "theme", "msg": "Freeing GPU for the LLM…"}))
            _wait_for_comfyui_unload(job_id)
            _push(job_id, "progress", json.dumps({
                "step": "theme", "msg": f"Theming card with the LLM ({_llm or 'default'})…"}))
            try:
                themer = Themer(model=_llm) if _llm else Themer()
                if req.theme_mode == "full":
                    # AI themes/renames the card, deck-style (one-card deck).
                    themed_cmd, _ = themer.theme_deck(
                        art_theme, card, [],
                        commander_prompt=req.commander_prompt,
                        style_guide_hint=_style_meta["style_guide_hint"],
                        themer_medium=_style_meta["themer_medium"],
                        themer_quality=_style_meta["themer_quality"],
                        commander_gender=req.face_gender,
                        lora_vocabulary=_style_meta.get("themer_vocabulary", ""),
                        auto_theme_tribes=False,
                        ro_mode=ro_mode,
                        theme_spec=req.theme_spec or None,
                        creativity=req.creativity or "balanced",
                        cancel_event=cancel_event,
                    )
                    tc = themed_cmd
                else:
                    # Author mode: keep the user's name/text, AI writes the art prompt.
                    tc = themer.theme_single_card(
                        card, art_theme,
                        commander_prompt=req.commander_prompt,
                        style_guide_hint=_style_meta["style_guide_hint"],
                        themer_medium=_style_meta["themer_medium"],
                        themer_quality=_style_meta["themer_quality"],
                        lora_vocabulary=_style_meta.get("themer_vocabulary", ""),
                        ro_mode=ro_mode,
                        theme_spec=req.theme_spec or None,
                        creativity=req.creativity or "balanced",
                        gender=req.face_gender,
                        want_flavor=not bool(card.get("flavor_text")),
                    )
                world_bible = getattr(themer, "_world_bible", {}) or {}
                _push(job_id, "progress", json.dumps({"step": "theme", "msg": "Theming complete", "pct": 100}))
            except ThemingCancelled:
                cancel_event.set()
            except Exception as e:
                print(f"  [card] theming failed: {e}")
                traceback.print_exc()
                _push(job_id, "progress", json.dumps({
                    "step": "theme",
                    "msg": f"⚠ Theming failed — writing the art prompt from the card itself. {e}",
                    "warning": True,
                    "hint": "Start the LLM gateway (E:\\llama\\start-llama-swap.bat) for AI-written "
                            "art prompts, names and flavor text."}))

        # Custom art prompt, or a fallback built from the card when theming was
        # skipped/failed. The old fallback used the bare theme string, so an
        # LLM-down build shipped the literal prompt "epic fantasy art centered on
        # <name>" — technically a prompt, but it threw away the type line, the
        # colour palette and the subject description the user had typed.
        if use_custom_prompt:
            prompt = custom_prompt
            if ro_mode:
                from themer import apply_ro_tokens as _apply_ro
                prompt = _apply_ro(prompt, card, override_text=req.commander_prompt)
            if tc is None:
                tc = ThemedCard(name, name, prompt, card.get("flavor_text", ""), card)
            else:
                # "AI themes everything" still gets to rename and reflavor, but the
                # ART is the user's — previously theme_deck's prompt won and the
                # text they typed was discarded without a word.
                tc.art_prompt = prompt
        elif tc is None:
            tc = ThemedCard(name, name,
                            _fallback_art_prompt(card, art_theme, req.commander_prompt,
                                                 _style_meta, ro_mode),
                            card.get("flavor_text", ""), card)

        # Author mode: never let AI flavor clobber a flavor the user actually wrote.
        if req.theme_mode != "full" and card.get("flavor_text"):
            tc.flavor_text = card["flavor_text"]

        # ── Set symbol + pips + frame ─────────────────────────────────────────
        _push(job_id, "progress", json.dumps({"step": "symbol", "msg": "Generating set symbol…"}))
        sym = generate_set_symbol(art_theme, emblem_prompt=req.emblem_prompt or "")
        sym_path = state.RENDER_DIR / job_id / "set_symbol.png"
        sym_path.parent.mkdir(parents=True, exist_ok=True)
        sym.save(sym_path)

        if req.custom_pips and req.generate_art:
            _ensure_comfyui_ready(job_id)
        _pip_emblem = _setup_deck_pips(job_id, req.custom_pips, art_theme, req.emblem_prompt or "")
        card_renderer.set_frame_style(req.frame_style or "builtin")
        if _pip_emblem is not None:
            sym = _pip_emblem

        render_out = state.RENDER_DIR / job_id / "cards"
        render_out.mkdir(parents=True, exist_ok=True)
        render_key = f"{_safe_name(name)}_000"
        deck_slug  = ("".join(c if c.isalnum() else "_" for c in name)[:28] + "_card_" + job_id[:8])

        # ── Persist checkpoint (deck of one) BEFORE art so a crash keeps the card ──
        def _persist(status: str, has_render: bool) -> dict:
            payload = {
                "status":          status,
                "mode":            "single_card",
                "commander":       _themed_card_to_dict(tc, deck_index=0, has_render=has_render),
                "deck":            [],
                "stats":           stats,
                # The user's theme, not the synthetic prompt seed (see `user_theme`).
                "theme":           user_theme,
                "art_theme_seed":  art_theme,
                "theme_spec":      req.theme_spec or {},
                "creativity":      req.creativity or "balanced",
                "theme_mode":      req.theme_mode,
                "art_prompt_mode": req.art_prompt_mode,
                # "" = the AI wrote the flavor and may re-roll it; non-empty = the
                # user typed it and no later run may touch it.
                "user_flavor":     (req.card.flavor_text or "").strip(),
                "commander_prompt": req.commander_prompt,
                "emblem_prompt":   req.emblem_prompt or "",
                "playstyle":       "Single Card",
                "bracket":         0,
                "art_style":       req.art_style,
                "checkpoint":      req.checkpoint or "",
                "model_speed":     req.model_speed,
                "gen_settings":    _gen_settings_to_dict(req.gen_settings),
                "generate_art":    req.generate_art,
                "deck_slug":       deck_slug,
                "face_key":        req.face_key or "",
                "face_gender":     req.face_gender,
                "crew_key":        "",
                "crew_gender":     "either",
                "crew_prompt":     "",
                "is_commander_deck": True,
                "user_name":       "",
                "llm_model":       req.llm_model or "",
                "border_theme":    req.border_theme or "",
                "frame_style":     req.frame_style or "builtin",
                "custom_pips":     req.custom_pips,
                "world_bible":     world_bible,
                "imported":        False,
                "built_at":        time.time(),
            }
            (state.RENDER_DIR / job_id / "deck.json").write_text(json.dumps(payload), encoding="utf-8")
            _jobs[job_id].update(payload)
            # deck.json carries "rendering" as its on-disk checkpoint state, but the
            # LIVE job must keep reporting "building" until the run really ends —
            # /api/deck/{id}/status is what a page refresh reconnects through, and
            # App.jsx drops the saved job for any status that isn't building/done.
            if status == "rendering":
                _jobs[job_id]["status"] = "building"
            return payload

        # Render the text-only proxy up front and persist it, so the card the user
        # authored survives ANY later failure — a cancel, a ComfyUI crash, a killed
        # process. Art generation below simply re-renders over the top when it
        # succeeds. Previously the first write happened after theming and the only
        # render happened after art, so cancelling left no deck.json at all and the
        # card was lost.
        def _render(art: "Optional[Path]" = None) -> None:
            processed = _replace_card_self_ref(card.get("oracle_text", ""), name, tc.themed_name)
            art_img = _PIL.open(art) if (art and art.exists()) else None
            img = render_card(
                tc.card, tc.themed_name, processed,
                art_image=art_img, set_symbol=sym,
                flavor_text=tc.flavor_text or "",
                border_theme=req.border_theme or "",
            )
            img.save(render_out / f"{render_key}.png", "PNG")
            _push(job_id, "card_ready", json.dumps({"key": render_key, "name": tc.themed_name}))

        _render()
        _persist("rendering", has_render=True)

        if cancel_event.is_set():
            _persist("cancelled", has_render=True)
            _push(job_id, "done", json.dumps({"job_id": job_id, "cancelled": True}))
            return

        # ── Art generation (optional) ─────────────────────────────────────────
        art_path: Optional[Path] = None
        if req.generate_art:
            _ensure_comfyui_ready(job_id)
            health = ImageGen.health_check()
            if not health["ok"]:
                _push(job_id, "progress", json.dumps({
                    "step": "art", "msg": f"⚠ Art generation skipped — {health['message']}",
                    "warning": True, "hint": health.get("hint", "")}))
            else:
                from themer import OLLAMA_MODEL as _DEFAULT_OLLAMA
                _push(job_id, "progress", json.dumps({"step": "art", "msg": "Freeing GPU for art generation…"}))
                _wait_for_ollama_evict(req.llm_model or _DEFAULT_OLLAMA, job_id)
                _push(job_id, "progress", json.dumps({"step": "art", "msg": "Waiting for GPU…"}))
                with _art_lock:
                    # A raising constructor (a bad checkpoint name, a ComfyUI that
                    # answered health_check and then died) used to take the whole
                    # build down through the outer handler — the user lost the card
                    # AND got a red "Build failed" alert. Art is optional; degrade.
                    gen = None
                    try:
                        gen = ImageGen(model_speed=req.model_speed, art_style=req.art_style,
                                       checkpoint=req.checkpoint,
                                       gen_settings=_resolve_gen_settings(req.gen_settings),
                                       frame_style=req.frame_style or "builtin")
                    except Exception as _ie:
                        print(f"  [card] ImageGen init failed: {_ie}")
                        traceback.print_exc()
                        _push(job_id, "progress", json.dumps({
                            "step": "art", "msg": f"⚠ Could not start the image generator — {_ie}",
                            "warning": True,
                            "hint": "The card is still rendered; use “New art for this card” to retry."}))
                    if gen is None or not gen.available:
                        if gen is not None:
                            _push(job_id, "progress", json.dumps({
                                "step": "art",
                                "msg": "⚠ ComfyUI not available — rendering without generated art.",
                                "warning": True}))
                    else:
                        face_comfy_name: Optional[str] = None
                        face_comfy_names: list[str] = []
                        if req.face_key and gen.face_method != "none":
                            _fp = get_face_paths(req.face_key)
                            if _fp:
                                # Upload EVERY photo, like the deck path does, so
                                # ReActor can average them into one face model. A
                                # single custom card is the case where the user is
                                # most likely to upload several angles of one person,
                                # and only the first was ever being used.
                                for _p in _fp:
                                    _n = gen.upload_face_to_comfy(_p)
                                    if _n:
                                        face_comfy_names.append(_n)
                                face_comfy_name = face_comfy_names[0] if face_comfy_names else None
                                if face_comfy_name:
                                    _push(job_id, "progress", json.dumps({
                                        "step": "art",
                                        "msg": f"Face loaded ({gen.face_method_label})"
                                               + (f" — blending {len(face_comfy_names)} photos"
                                                  if len(face_comfy_names) > 1 else "")}))
                        _push(job_id, "progress", json.dumps({
                            "step": "art", "msg": f"[1/1] {tc.themed_name}",
                            "card_num": 1, "total": 1, "card_name": tc.themed_name,
                            "has_face": face_comfy_name is not None, "pct": 50}))
                        t0 = time.time()
                        try:
                            art_path = gen.generate(
                                tc.art_prompt,
                                str(state.ART_DIR / deck_slug / _safe_name(name)),
                                face_comfy_name=face_comfy_name,
                                face_comfy_names=face_comfy_names or None,
                                face_gender=req.face_gender,
                                card_type=card.get("type_line", ""),
                                cancel_event=cancel_event,
                            )
                        except Exception as _ge:
                            print(f"  [card] art gen raised: {_ge}")
                            traceback.print_exc()
                            _push(job_id, "progress", json.dumps({
                                "step": "art", "msg": f"⚠ Art generation failed — {_ge}",
                                "warning": True}))
                        _push(job_id, "progress", json.dumps({
                            "step": "art", "msg": f"[1/1] {tc.themed_name} — {'OK' if art_path else 'FAIL'}",
                            "card_num": 1, "total": 1, "pct": 100,
                            "last_ok": art_path is not None, "elapsed": round(time.time() - t0)}))
                _wait_for_comfyui_unload(job_id)

        # ── Re-render with the art (the text-only proxy is already on disk) ────
        if art_path:
            _push(job_id, "progress", json.dumps({"step": "render", "msg": "Rendering card…"}))
            _render(art_path)

        _persist("cancelled" if cancel_event.is_set() else "done", has_render=True)
        _push(job_id, "done", json.dumps(
            {"job_id": job_id, **({"cancelled": True} if cancel_event.is_set() else {})}))

    except Exception as e:
        _mark_job_error(job_id, e)
    finally:
        _finalize_job(job_id)
