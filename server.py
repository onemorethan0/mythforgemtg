"""
FastAPI backend for the Commander Deck Builder.

Endpoints:
  POST /api/commander/search          fuzzy commander lookup
  GET  /api/playstyles                list of playstyle options
  POST /api/deck/build                start async deck build → {job_id}
  GET  /api/deck/{job_id}/status      poll build status + progress events
  GET  /api/deck/{job_id}             full deck payload once complete
  GET  /api/deck/{job_id}/card-image/{safe_name}   rendered card PNG
  GET  /api/deck/{job_id}/set-symbol  deck set emblem PNG
  GET  /*                             serve React frontend static files

SSE (Server-Sent Events) used for streaming progress during build.
"""
from __future__ import annotations

import asyncio
import io
import hashlib
import json
import logging
import os
import threading
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ── Local modules ─────────────────────────────────────────────────────────────
import deck_import
import commander_analysis
from commander_analysis import build_commander_profile
from deck_builder       import (DeckBuilder, compute_stats, aggregate_duplicates,
                                SOURCE_SCRYFALL)
from collection         import (
    load_owned_names, owned_count, suite_collection_path,
    load_collection, add_card as coll_add_card, set_count as coll_set_count,
    remove_card as coll_remove_card, bulk_import as coll_bulk_import, owned_key,
    write_collection as coll_write, set_printing as coll_set_printing,
    bulk_apply as coll_bulk_apply, row_id as coll_row_id,
    set_count_by_id as coll_set_count_by_id, remove_by_id as coll_remove_by_id,
    set_printing_by_id as coll_set_printing_by_id, find_by_id as coll_find_by_id,
    normalize_finish as coll_normalize_finish, _merge_row as _coll_merge_row,
)
import scryfall_prints
import collection_repair as coll_repair
from collection_index    import (GROUP_BYS, group_rows, facets as coll_facets, filter_rows, sort_rows,
                                 print_price as coll_print_price, treatments_of as coll_treatments_of)
from collection_stats    import collection_stats
from playstyle          import (
    PLAYSTYLES, PLAYSTYLE_ORDER, resolve_themes, get_slot_adjustments,
)
from themer             import Themer
from image_gen          import ImageGen, _is_flux, _is_sd35, _is_sdxl, _is_krea, _is_qwen
from exporter           import build_zip, build_pdf, build_video_zip
from model3d            import Model3DGen, generate_commander_3d
import edhrec_lift

# Imported ahead of the log tee, as when every route lived in this file: image_gen and
# model3d swap sys.stdout for a UTF-8 wrapper on import (the tee must wrap it, not be
# replaced by it), and card_renderer prints its symbol-cache warm-up before the tee.
import image_gen  # noqa: F401,E402
import card_renderer  # noqa: F401,E402
import model3d  # noqa: F401,E402

# ── In-memory log capture ──────────────────────────────────────────────────────
# Tee stdout/stderr into a bounded ring buffer so the running server's output
# (startup checks, pipeline prints, tracebacks, uvicorn access logs) can be
# viewed from inside the app via /api/logs — regardless of how the process was
# launched (console, redirected file, or detached with no console at all).
import sys as _sys

from api.logbuffer import _LOG_BUFFER, _TeeStream
from datetime import datetime as _dt


# Wrap whatever stdout/stderr are at this point (model3d already installed a
# UTF-8 wrapper on import). Wrapping happens before uvicorn.run() so uvicorn's
# log handlers bind to the tee and access logs are captured too.
_sys.stdout = _TeeStream(_sys.stdout)
_sys.stderr = _TeeStream(_sys.stderr)

from api import state
from api.state import (
    _require_job_id,
    _jobs,
    _progress,
    _RATE_LIMIT_WINDOW,
    _RATE_LIMIT_BUILD_REQUESTS,
    _RATE_LIMIT_CHAT_REQUESTS,
    _CHAT_RATE_LIMIT_KEY,
    _art_lock,
    _3d_jobs,
    _3d_progress,
    _scryfall,
    _check_rate_limit,
    _cleanup_expired_jobs,
    _push,
    _sse_stream,
    _serializable_job,
    _load_deck_from_disk,
)
from api.models import (
    SearchRequest,
    GenSettingsModel,
    _resolve_gen_settings,
    BuildRequest,
    RebuildRequest,
    RegenCardsRequest,
    AnimateCardsRequest,
    RethemeRequest,
    CardBuildRequest,
)
from api.collection_data import (
    _annotate_owned,
    _save_prices,
    _collection_summary,
    _csv_param,
    _enriched_collection,
)
from api.cards import (
    _free_all_vram,
    _safe_name,
    _imported_card_to_stored,
    _is_single_card,
    _download_art_to,
    _resolve_card_source,
    _resolve_partners,
)
from api.jobs_build import (
    _run_build,
    _run_card_build,
)
from api.jobs_rebuild import (
    _run_rebuild,
)
from api.jobs_regen import (
    _run_regen_cards,
    _run_animate_cards,
)
from api.jobs_retheme import (
    _run_retheme,
)


# ── App setup ─────────────────────────────────────────────────────────────────

# Lifespan context manager for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle app startup and shutdown with proper lifecycle management."""
    # STARTUP
    import sys
    print("\n" + "="*70, flush=True)
    print("MYTH FORGE - STARTUP CHECKS", flush=True)
    print("="*70, flush=True)
    sys.stdout.flush()

    # Run startup checks
    _ensure_frontend_built()
    sys.stdout.flush()
    _ensure_ollama_models_ready()
    sys.stdout.flush()
    # Local Scryfall card store (name lookups with no API call). Refreshed in a background
    # thread when older than a week, so startup and requests never wait on the ~30 MB
    # download; until it exists, lookups fall back to the live API as before.
    import scryfall_bulk
    scryfall_bulk.refresh_async()
    import scryfall_prints   # per-printing store (default_cards); same lifecycle
    scryfall_prints.refresh_async()

    print("="*70, flush=True)
    print("FRONTEND READY - If you made code changes, hard refresh your browser:", flush=True)
    print("  Windows/Linux: Ctrl+Shift+R  |  macOS: Cmd+Shift+R", flush=True)
    print("="*70 + "\n", flush=True)
    sys.stdout.flush()

    # Start periodic cleanup of old jobs in the background
    async def cleanup_loop():
        """Run job cleanup every hour."""
        while True:
            await asyncio.sleep(3600)  # 1 hour
            _cleanup_expired_jobs()

    cleanup_task = asyncio.create_task(cleanup_loop())

    # Yield control back to the application
    yield

    # SHUTDOWN
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

logger = logging.getLogger(__name__)

app = FastAPI(title="Myth Forge", version="1.3", lifespan=lifespan)

# Bind tightly to localhost — this app has no auth layer. If you need
# LAN access, add an auth header check and expand allow_origins explicitly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


def _run_frontend_build(frontend_dir: Path, verb: str) -> None:
    """`npm run build` in `frontend_dir`, reporting the outcome on the startup log.

    npm is resolved with `shutil.which`: on Windows it is `npm.cmd`, and CreateProcess
    does not apply PATHEXT, so a bare `["npm", ...]` raised WinError 2 on every start and
    the app silently served a stale bundle (found 2026-10-23: a week of UI changes unbuilt).
    """
    import shutil
    import subprocess

    npm = shutil.which("npm")
    if not npm:
        print("  [startup] [X] Frontend build skipped: npm not on PATH "
              "(install Node.js, then run `npm run build` in frontend/)", flush=True)
        return
    try:
        result = subprocess.run([npm, "run", "build"], cwd=frontend_dir,
                                capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print("  [startup] [X] Frontend build timed out (>120s)", flush=True)
        return
    except Exception as e:
        print(f"  [startup] [X] Frontend build error: {e}", flush=True)
        return
    if result.returncode == 0:
        print(f"  [startup] [OK] Frontend {verb} successfully", flush=True)
    else:
        print(f"  [startup] [X] Frontend build failed: {(result.stderr or result.stdout)[-400:]}",
              flush=True)


def _ensure_frontend_built():
    """Check if frontend needs rebuilding and rebuild if necessary.

    Compares modification times of frontend source (src/) and built output (dist/).
    If any source file is newer than the build, trigger a rebuild.
    """
    frontend_dir = Path(__file__).parent / "frontend"
    src_dir = frontend_dir / "src"
    dist_dir = frontend_dir / "dist"

    if not src_dir.exists():
        print("  [startup] [!] Frontend source not found (frontend/src/)", flush=True)
        return

    if not dist_dir.exists():
        print("  [startup] [!] Frontend dist not found — rebuilding...", flush=True)
        _run_frontend_build(frontend_dir, "built")
        return

    # Check if rebuild needed: if any src file is newer than dist files
    try:
        dist_time = max(
            (f.stat().st_mtime for f in dist_dir.rglob("*") if f.is_file()),
            default=0
        )
        src_time = max(
            (f.stat().st_mtime for f in src_dir.rglob("*") if f.is_file()),
            default=0
        )

        if src_time > dist_time:
            print("  [startup] [!] Frontend source changed — rebuilding...", flush=True)
            _run_frontend_build(frontend_dir, "rebuilt")
        else:
            print("  [startup] [OK] Frontend is up to date", flush=True)
    except Exception as e:
        print(f"  [startup] [!] Could not check frontend build status: {e}", flush=True)


def _ensure_ollama_models_ready():
    """Check that the LLM backend (llama.cpp via llama-swap, or Ollama) is
    reachable. Does NOT load models (would block startup)."""
    from themer import LLM_BACKEND, OLLAMA_MODEL, installed_models, llm_endpoint_base

    label = "llama.cpp (llama-swap)" if LLM_BACKEND == "llamacpp" else "Ollama"
    print(f"\n[startup] Checking {label} connectivity at {llm_endpoint_base()}...", flush=True)

    models = installed_models()
    if models:
        print(f"  [startup] [OK] {label} reachable - {len(models)} model(s) available", flush=True)
        if OLLAMA_MODEL in models:
            print(f"  [startup] [OK] Default model available: {OLLAMA_MODEL}", flush=True)
        else:
            print(f"  [startup] [!] Default model '{OLLAMA_MODEL}' not in list: {sorted(models)}", flush=True)
            print(f"  [startup]     A fallback model will be used; check your backend config.", flush=True)
    else:
        print(f"  [startup] [FAIL] {label} not reachable at {llm_endpoint_base()}", flush=True)
        if LLM_BACKEND == "llamacpp":
            print(f"  [startup]        Start the gateway: E:\\llama\\start-llama-swap.bat", flush=True)
        else:
            print(f"  [startup]        Start Ollama before running the deck builder", flush=True)


# ── VRAM management helpers ──────────────────────────────────────────────────
# RTX 3090 = 24 GB.  FLUX.1-dev-fp8 ≈ 12 GB, qwen3:14b ≈ 10 GB,
# qwen3.6:27B ≈ 23 GB.  Running any two simultaneously = OOM → Windows crash.
#
# Critical insight: Ollama's /api/ps dropping a model name does NOT mean CUDA
# has released the memory.  PyTorch/CUDA keeps pages cached for fast re-use.
# We must wait for *physical VRAM* to drop to a safe level, not just for the
# model to disappear from the process list.  This is why 20s was too short for
# 27B models — the OS page reclaim takes 30-60 s for large allocations.
#
# FLUX dev-fp8 needs ~12 GB.  LoRAs add ~1-3 GB.  Overhead ~1 GB.
# → We need at least 16 GB free before loading FLUX.
# → We warn and wait up to 120 s.  If VRAM doesn't clear in time we abort art
#   gen rather than letting Windows crash the whole machine.

# VRAM gating moved to services.py (same concern as the startup helpers).
from services import (  # noqa: E402
    _comfyui_vram_free_gb,
    _wait_for_comfyui_unload,
    _wait_for_ollama_evict,
)


# ── Routes ─────────────────────────────────────────────────────────────────────

class ImportPreviewRequest(BaseModel):
    source:        str  = Field("", max_length=20000)  # URL or pasted decklist text
    force_refresh: bool = False                          # bypass the on-disk cache


# --- MythGauntlet strength API (Myth Suite contract C3) ---------------------------------
# Simulation-grounded deck strength: MythGauntlet plays thousands of games and returns a
# measured Power Profile. It is the SOLE bracket authority — Forge used to carry its own
# heuristic estimator (deck_analysis.py) as a fallback and the import preview rendered
# both, which let the copies drift: Forge's still applied the tutor restrictions the
# October 2025 bracket update removed. The duplicate is deleted; when :8020 is down the
# UI says so rather than substituting a second, worse opinion.
MYTHGAUNTLET_URL = os.getenv("MYTHGAUNTLET_URL", "http://127.0.0.1:8020").rstrip("/")


def _job_partners(job: dict) -> list[dict]:
    """The rest of the command zone for a stored job, in `_deck_to_lines`'s shape.

    `job["partners"]` is persisted as plain names (see `_run_build`'s checkpoint) — this
    is the one place that turns them back into the `{"name": ...}` dicts every
    `_gauntlet_*` helper expects."""
    return [{"name": n} for n in (job.get("partners") or [])]


def _deck_to_lines(commander, deck, partners=None) -> str:
    """Render an imported deck as MythGauntlet's decklist text format.

    `partners` is the rest of the command zone. `Deck.commanders` (mythgauntlet's own
    parser, model/deck.py) reads every line under the "Commander:" header, so a second
    line here is enough for the engine to resolve BOTH cards and union their colour
    identity in `manabase.analyze` — mirroring `deck_quality.assess_colors`'s own
    partners= fix. Omitting it (as this function always did) makes the strength engine
    and the mentor measure a partner deck's manabase against the LEAD commander's colours
    alone: a real WBUG manabase (duals/fetches that fix all four colours) reads back as
    "0 U sources, 0 G sources" because those colours sit outside the half-identity.
    Found live 2026-08-25 on Tymna the Weaver + Thrasios, Triton Hero.
    """
    lines = []
    if commander and commander.get("name"):
        lines += ["Commander:", f"1 {commander['name']}"]
        for p in (partners or []):
            if p.get("name"):
                lines.append(f"1 {p['name']}")
        lines.append("")
    lines.append("Deck:")
    for c in deck:
        name = c.get("name", "")
        if name:
            lines.append(f"{c.get('quantity', 1)} {name}")
    return "\n".join(lines)


_ENGINE_FP_CACHE = {"at": 0.0, "fp": None}


def _engine_fingerprint() -> str | None:
    """The running engine's `model_fingerprint` (60 s cache), None when unknown.

    A cached `last_measure` from different scoring code is stale: the deck page used to
    show a Sep 4 Resilience 88 as current beside a fresh 41 for the same list, because
    `engine_version` never moved through the axis re-models. Unknown (engine down) is not
    stale - there is nothing better to show."""
    now = time.time()
    if _ENGINE_FP_CACHE["fp"] is not None and now - _ENGINE_FP_CACHE["at"] < 60:
        return _ENGINE_FP_CACHE["fp"]
    try:
        fp = requests.get(f"{MYTHGAUNTLET_URL}/health", timeout=1.5).json().get("model_fingerprint")
    except Exception:
        return None
    _ENGINE_FP_CACHE.update(at=now, fp=fp)
    return fp


def _gauntlet_analyze(commander, deck, partners=None):
    """Simulation-grounded strength from MythGauntlet; None if the service is unavailable."""
    try:
        resp = requests.post(
            f"{MYTHGAUNTLET_URL}/analyze",
            json={
                "deck": _deck_to_lines(commander, deck, partners),
                "name": (commander or {}).get("name") or "deck",
                "runs": 300,
                "resilience": True,
                "combos": True,  # graded combo gate: real wincons vs durdles (Spellbook, cached)
            },
            # Measured 2026-10-06: a real 89-card deck takes ~38s through /analyze
            # (runs=300 + resilience + combos), so the old 25s read timeout reported
            # a healthy engine as "unreachable". 120s leaves margin for a loaded box.
            timeout=120,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "engine_version": data.get("engine_version"),
            "model_fingerprint": data.get("model_fingerprint"),
            "power_profile": data.get("power_profile"),
            "combos": data.get("combos"),  # graded in-deck combos for the strength panel
            # Deck-specific narrative (archetype/gameplan/pod placement/key cards/strengths
            # & weaknesses) -- fully computed by the engine's own insight.py, deterministic
            # and free (no extra simulation), but previously dropped here: this function
            # reshapes the /analyze response and only ever forwarded the three keys above.
            "insight": data.get("insight"),
            "unresolved": (data.get("deck") or {}).get("unresolved", []),
        }
    except Exception as e:
        print(f"  [import-preview] MythGauntlet strength API unavailable: {e}")
        return None


def _deck_archetypes(job: dict) -> list[str]:
    """The deck's OWN detected archetypes, for the engine's redundancy targets.

    The engine judges "what does this deck have too much of" against ONE population
    baseline unless it is told what the deck is trying to DO, and that reads a deck's plan
    as oversupply: a spellslinger deck is scored against a population whose median deck
    plays ZERO counterspells, so its interaction becomes the cut pool. The detector lives
    here (`deck_themes`), not in the engine on :8020, so this is the handoff.

    PREFER THE PERSISTED BLOCK. `stats.archetypes` was computed by `compute_stats` from the
    deck's REAL cards, before theming touched them. Re-deriving it from the stored entries
    is second best on purpose, because theming MUTATES the text those rules read: a tribe
    reskin rewrites rules text ("equip Knight" -> "equip Cowboy") and the self-reference
    pass swaps the card's own name in. `original_type_line` is the un-reskinned line and is
    what the fallback reads; the oracle text has no such rewind, so on a tribe-reskinned
    deck built before `stats.archetypes` existed this can under-detect.

    Under-detection is the safe failure: no archetype means the population baseline, which
    is what the engine did before this existed. Never raises - advice must not fail because
    a descriptive figure could not be derived.
    """
    try:
        stored = ((job.get("stats") or {}).get("archetypes") or {}).get("deck")
        if stored:
            return list(stored)
        import deck_themes
        return deck_themes.detect_deck_themes([
            {
                "name": c.get("original_name", ""),
                "type_line": c.get("original_type_line") or c.get("type_line", ""),
                "oracle_text": c.get("oracle_text", ""),
            }
            for c in (job.get("deck") or [])
        ])
    except Exception:      # noqa: BLE001 - a missing archetype only costs precision
        return []


def _gauntlet_advise(commander, deck, axis=None, themes=None, partners=None):
    """Owned-card upgrade suggestions from MythGauntlet's ablation advisor.

    Returns the advise JSON, {"error": detail} for a meaningful 400 (no collection
    exported / bad axis), or None when the service is unreachable.

    `themes` are the deck's own archetypes (see `_deck_archetypes`); without them the
    engine judges every role against one population baseline and offers the deck its own
    plan as the cut pool.
    """
    try:
        payload = {
            "deck": _deck_to_lines(commander, deck, partners),
            "name": (commander or {}).get("name") or "deck",
            "runs": 300,
            # The advisor ranks owned candidates by TARGET-AXIS relevance + commander fit
            # before spending the eval budget, then returns a NON-OVERLAPPING package
            # (distinct cuts). cut_pool=6 gives up to 6 replaceable slots so the package
            # can be more than 3 swaps; max_eval=16 relevant adds compete for them.
            # NOT "~60s warm" — that estimate was swept at max_eval=10, runs=60.
            # MEASURED 2026-08-26 at this exact config against a real 99-card deck with
            # ComfyUI + llama-swap warm-but-idle: 583s (96 analyses, ~6s/analysis at
            # runs=300). `_gauntlet_advise` now runs off the request thread (see
            # `advise_deck`'s docstring), so 900s just needs real margin over that
            # measurement, not to double as a UI-responsiveness budget.
            "max_eval": 16,
            "cut_pool": 6,
        }
        if themes:
            payload["themes"] = list(themes)
        if axis:
            payload["axis"] = axis
        lift = edhrec_lift.lift_map((commander or {}).get("name") or "")
        if lift:
            payload["lift"] = lift
        resp = requests.post(f"{MYTHGAUNTLET_URL}/advise", json=payload, timeout=900)
        if resp.status_code == 400:
            try:
                return {"error": resp.json().get("detail", "advise failed")}
            except Exception:
                return {"error": "advise failed"}
        if resp.status_code != 200:
            return None
        return resp.json()
    except requests.Timeout:
        # Reachable but slower than the budget — saying "unreachable" here sent the
        # 2026-10-23 investigation after the wrong process (the cause was sim cost).
        print("  [advise] MythGauntlet /advise timed out after 900s")
        return {"error": "The upgrade search took longer than 15 minutes and was stopped. "
                         "The strength engine is running but overloaded — try again, or pick "
                         "a single target axis."}
    except Exception as e:
        print(f"  [advise] MythGauntlet strength API unavailable: {e}")
        return None


def _gauntlet_card_impact(commander, deck, card_name, themes=None, partners=None):
    """Would ONE named card help or hurt this deck (MythGauntlet /card-impact).

    Same shape as _gauntlet_advise: the JSON on success, {"error": detail} for a
    meaningful 400/404 (unknown card name is the common one, and the user needs to see
    that rather than a generic failure), None when the service is unreachable.

    runs is lower than /advise's because this re-simulates the whole Power Profile per
    candidate cut and the user is waiting on it interactively; cut_pool=3 keeps it to
    three analyses.

    `themes` are the deck's own archetypes (see `_deck_archetypes`) - same handoff /advise
    uses, and needed here for the same reason: without them the slot this card is tested
    against can be part of the deck's own plan.
    """
    try:
        payload = {
            "deck": _deck_to_lines(commander, deck, partners),
            "name": (commander or {}).get("name") or "deck",
            "card": card_name,
            "runs": 200,
            "cut_pool": 3,
            "themes": list(themes or []),
        }
        lift = edhrec_lift.lift_map((commander or {}).get("name") or "")
        if lift:
            payload["lift"] = lift
        resp = requests.post(
            f"{MYTHGAUNTLET_URL}/card-impact",
            json=payload,
            timeout=120,
        )
        if resp.status_code in (400, 404):
            try:
                return {"error": resp.json().get("detail", "card lookup failed")}
            except Exception:
                return {"error": "card lookup failed"}
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"  [card-impact] MythGauntlet strength API unavailable: {e}")
        return None


def _gauntlet_mentor_chat(commander, deck, question, history=None, model=None, themes=None,
                           partners=None, offmeta=None, advice=None):
    """Deck Mentor chat turn from MythGauntlet's tool-calling loop + claim-budget gate
    (docs/SPEC_deck_mentor.md Phase 2). Same shape as `_gauntlet_advise`/
    `_gauntlet_card_impact`: JSON on success, {"error": detail} for a meaningful 400/503
    the caller should show verbatim, None when the service process itself is unreachable.

    Unlike the other two, a 503 from :8020 here can mean "the engine is down" (None,
    same as always) OR "the engine is up but hasn't run fetch-rules yet" (a real detail
    message worth showing) -- both are surfaced as {"error": ...} rather than being
    collapsed into the generic "unreachable" case, since only the latter is actionable
    with "start the server"; the former needs "run fetch-rules" instead.

    `offmeta` is this deck's own persisted `lift_stats.stats_block` reading (see
    `mentor_chat_deck`) -- the engine has no EDHREC cache of its own, so this is a
    pass-through of what Forge already computed, exactly like `themes` already is.

    `advice` is `_valid_advice(job)`: the deck's still-current cached full swap searches
    (D2), `{axis key: {"result", "computed_at"}}`, for the engine's `get_measured_swaps`.
    """
    try:
        payload = {
            "deck": _deck_to_lines(commander, deck, partners),
            "name": (commander or {}).get("name") or "deck",
            "question": question,
            "history": history or [],
        }
        if model:
            payload["model"] = model
        if themes:
            payload["themes"] = list(themes)
        if offmeta:
            payload["offmeta"] = offmeta
        if advice:
            payload["advice"] = advice
        resp = requests.post(f"{MYTHGAUNTLET_URL}/mentor/chat", json=payload, timeout=120)
        if resp.status_code in (400, 503):
            try:
                return {"error": resp.json().get("detail", "mentor chat failed")}
            except Exception:
                return {"error": "mentor chat failed"}
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"  [mentor] MythGauntlet strength API unavailable: {e}")
        return None


class MentorChatDeckRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)
    model: Optional[str] = None  # None -> the engine's own default (qwen3:14b)


@app.post("/api/deck/{job_id}/mentor")
def mentor_chat_deck(job_id: str, req: MentorChatDeckRequest, request: Request):
    """Ask the Deck Mentor a question about this finished deck (docs/SPEC_deck_mentor.md
    Phase 2). Every reply is checked against that turn's own tool calls before it comes
    back — `gated: false` in the response means the answer is an honest "I'm not sure"
    rather than a claim that failed verification, never a silently-stripped one.
    """
    _require_job_id(job_id)
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip + _CHAT_RATE_LIMIT_KEY, _RATE_LIMIT_CHAT_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_CHAT_REQUESTS} requests per {_RATE_LIMIT_WINDOW}s")
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has no deck for the mentor to read.")
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in cards
    ]
    result = _gauntlet_mentor_chat(
        commander, deck, req.question.strip(), history=req.history, model=req.model,
        themes=_deck_archetypes(job), partners=_job_partners(job),
        offmeta=(job.get("stats") or {}).get("offmeta") or None,
        advice=_valid_advice(job) or None,
    )
    if result is None:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


def _gauntlet_breakdown(commander, deck, themes=None, partners=None):
    """The engine's /breakdown block (the mentor's own role table, interaction coverage,
    curve, colour sources and per-card roles); {"error": detail} on a 400, None when the
    service is unreachable."""
    try:
        resp = requests.post(
            f"{MYTHGAUNTLET_URL}/breakdown",
            json={"deck": _deck_to_lines(commander, deck, partners),
                  "name": (commander or {}).get("name") or "deck",
                  "themes": list(themes or [])},
            timeout=120,
        )
        if resp.status_code == 400:
            try:
                return {"error": resp.json().get("detail", "breakdown failed")}
            except ValueError:
                return {"error": "breakdown failed"}
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"  [breakdown] MythGauntlet strength API unavailable: {e}")
        return None


# Bump when the engine's /breakdown payload gains fields, so cached breakdowns re-measure once.
# 2: per-card `commander_synergy`.
BREAKDOWN_SCHEMA = 2


@app.post("/api/deck/{job_id}/breakdown")
def deck_breakdown(job_id: str, refresh: bool = False):
    """The Deck Mentor's measurements for charts and the deck view's group-by-role.

    Persisted in deck.json under `breakdown` with the hash of the decklist text and the
    themes it was measured with, so the panel opens instantly on a revisit and a swap,
    rebuild or edit recomputes it rather than charting the old list. `refresh=true`
    re-measures anyway (a tagger change in the engine moves roles without moving the hash).
    """
    _require_job_id(job_id)
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    if not (job.get("deck") or []):
        raise HTTPException(400, "A single-card build has no deck to break down.")
    commander, deck = _job_deck_inputs(job)
    partners = _job_partners(job)
    themes = _deck_archetypes(job)
    key = hashlib.sha1(json.dumps(
        [BREAKDOWN_SCHEMA, _deck_to_lines(commander, deck, partners), sorted(themes)]
    ).encode("utf-8")).hexdigest()
    cached = job.get("breakdown") or {}
    if not refresh and cached.get("key") == key and cached.get("data"):
        return {**cached["data"], "computed_at": cached.get("computed_at"), "cached": True}
    data = _gauntlet_breakdown(commander, deck, themes=themes, partners=partners)
    if data is None:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        )
    if "error" in data:
        raise HTTPException(400, data["error"])
    stamp = {"key": key, "data": data, "computed_at": _dt.now().isoformat(timespec="seconds")}
    try:
        p = state.RENDER_DIR / job_id / "deck.json"
        if p.exists():
            disk_data = json.loads(p.read_text(encoding="utf-8"))
            disk_data["breakdown"] = stamp
            p.write_text(json.dumps(disk_data), encoding="utf-8")
        if job_id in _jobs:
            _jobs[job_id]["breakdown"] = stamp
    except Exception as e:
        print(f"  [breakdown] could not persist: {e}")
    return {**data, "computed_at": stamp["computed_at"], "cached": False}


class MentorFeedbackDeckRequest(BaseModel):
    turn_id: str = Field(min_length=1)
    rating: str = Field(description="'up' or 'down'")
    note: Optional[str] = Field(default=None, max_length=1000)


@app.post("/api/deck/{job_id}/mentor/feedback")
def mentor_feedback_deck(job_id: str, req: MentorFeedbackDeckRequest, request: Request):
    """Thumbs up/down on a logged mentor turn (docs/SPEC_deck_mentor.md, Phase 3
    prerequisite). `job_id` isn't sent to the engine -- `turn_id` alone identifies the
    logged record on :8020's side -- but the route is scoped under the deck anyway so a
    stray or spoofed turn_id from a different session can't be submitted from a page that
    was never shown that turn_id in the first place.
    """
    _require_job_id(job_id)
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip + _CHAT_RATE_LIMIT_KEY, _RATE_LIMIT_CHAT_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_CHAT_REQUESTS} requests per {_RATE_LIMIT_WINDOW}s")
    try:
        resp = requests.post(
            f"{MYTHGAUNTLET_URL}/mentor/feedback",
            json={"turn_id": req.turn_id, "rating": req.rating, "note": req.note},
            timeout=15,
        )
    except Exception as e:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        ) from e
    if resp.status_code == 400:
        detail = "invalid feedback"
        try:
            detail = resp.json().get("detail", detail)
        except ValueError:
            pass
        raise HTTPException(400, detail)
    if resp.status_code != 200:
        raise HTTPException(502, "Feedback was not recorded.")
    return resp.json()


class CardImpactDeckRequest(BaseModel):
    card: str = Field(min_length=1, max_length=200)


def _narrate_suggestions(result: dict, job: dict) -> dict:
    """Rewrite each swap's `reason` as prose, keeping the template as the fallback.

    The engine ships a `brief` per suggestion — the facts the swap is entitled to claim — and
    `swap_narrative` turns one into two or three sentences, then GATES the result against that
    brief. A draft that names a card outside the swap, cites a number nobody measured, calls a
    card something its vector does not show, or claims redundancy on a deck that over-supplies
    nothing is thrown away and the deterministic sentence stands.

    That fallback is what makes the gate affordable: refusing a draft costs polish, while
    shipping an invented claim costs the one thing an MTG-facing tool cannot afford. Every
    failure path here — no brief, LLM down, every attempt rejected — lands on the template.

    The original is preserved as `reason_template` rather than discarded, so the UI and any
    debugging can see both.
    """
    suggestions = result.get("suggestions") or []
    if not suggestions:
        return result
    try:
        import swap_narrative
    except Exception:                       # noqa: BLE001 - advice must never fail on this
        return result

    # Every card the deck actually plays, so the gate can catch an invented one. Read from the
    # stored deck rather than the engine payload: this is the only place that knows the list.
    deck_names = {c.get("original_name", "") for c in (job.get("deck") or [])}
    deck_names.discard("")
    commander = (job.get("commander") or {}).get("original_name")
    if commander:
        deck_names.add(commander)

    kept = 0
    for suggestion in suggestions:
        brief = suggestion.get("brief")
        if not brief:
            continue
        try:
            text = swap_narrative.narrate(brief, deck_card_names=deck_names)
        except Exception:                   # noqa: BLE001 - never fail the route
            text = None
        if text:
            suggestion["reason_template"] = suggestion.get("reason", "")
            suggestion["reason"] = text
            kept += 1
    if suggestions:
        print(f"  [advise] narrated {kept}/{len(suggestions)} suggestions "
              f"({len(suggestions) - kept} kept the measured template)")
    return result


class AdviseDeckRequest(BaseModel):
    axis: Optional[str] = None  # None -> the deck's weakest axis
    narrate: bool = True        # rewrite each reason as prose (gated; falls back silently)


@app.post("/api/deck/{job_id}/card-impact")
def card_impact_deck(job_id: str, req: CardImpactDeckRequest):
    """Ask whether ONE named card would help or hurt this finished deck, and why.

    Legality is judged before anything is simulated, so an off-colour or banned card comes
    back as a refusal with the reason rather than a power score for a card you cannot play.
    """
    _require_job_id(job_id)
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has no deck to measure against.")
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in cards
    ]
    result = _gauntlet_card_impact(commander, deck, req.card.strip(),
                                   themes=_deck_archetypes(job), partners=_job_partners(job))
    if result is None:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


def _suite_collection_mtime() -> float | None:
    """mtime of the Myth Suite collection.csv the advisor suggests from, None when absent.
    A cached swap search is only valid while the collection it searched is unchanged."""
    try:
        return suite_collection_path().stat().st_mtime
    except OSError:
        return None


def _advice_deck_hash(commander, deck, partners=None) -> str:
    """Identity of the deck a swap search ran on: sha1 of the exact decklist text the engine
    is sent. A swap, rebuild or edit changes it, so stale advice is never shown."""
    return hashlib.sha1(_deck_to_lines(commander, deck, partners).encode("utf-8")).hexdigest()


def _job_deck_inputs(job: dict) -> tuple[dict, list[dict]]:
    """(commander, deck) in the `{"name": ...}` shape every `_gauntlet_*` helper takes."""
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in (job.get("deck") or [])
    ]
    return commander, deck


def _valid_advice(job: dict) -> dict:
    """The deck's `advice_cache` entries that still describe THIS deck and THIS collection
    (deck hash and collection mtime both match), as `{axis key: {"result", "computed_at"}}`.
    Anything else is dropped -- the mentor then says no full search has been run."""
    cache = job.get("advice_cache") or {}
    if not cache:
        return {}
    commander, deck = _job_deck_inputs(job)
    deck_hash = _advice_deck_hash(commander, deck, _job_partners(job))
    mtime = _suite_collection_mtime()
    return {
        key: {"result": e["result"], "computed_at": e.get("computed_at")}
        for key, e in cache.items()
        if isinstance(e, dict) and isinstance(e.get("result"), dict)
        and e.get("deck_hash") == deck_hash and mtime is not None
        and e.get("collection_mtime") == mtime
    }


def _persist_advice(deck_job_id: str, axis_key: str, entry: dict) -> None:
    """Write `advice_cache[axis_key] = entry` into the deck's deck.json (and the in-memory job),
    the same read-modify-write `/measure` uses for `last_measure`. Deliberately NOT in
    `_PROVENANCE_KEYS`: a rebuilt/rethemed deck is a different deck and must not inherit it."""
    try:
        p = state.RENDER_DIR / deck_job_id / "deck.json"
        if p.exists():
            disk = json.loads(p.read_text(encoding="utf-8"))
            disk.setdefault("advice_cache", {})[axis_key] = entry
            p.write_text(json.dumps(disk), encoding="utf-8")
        mem = _jobs.get(deck_job_id)
        if mem is not None:
            mem.setdefault("advice_cache", {})[axis_key] = entry
    except Exception as e:
        print(f"  [advise] could not persist advice_cache: {e}")


def _run_advise_job(advise_job_id: str, commander, deck, axis, themes, partners, narrate, deck_job,
                    deck_job_id: str | None = None):
    """Background body of `advise_deck` — see that route for why this is async.

    Mirrors `_run_style_sample`: write status/result/error into `_jobs[advise_job_id]`
    rather than returning, since this runs via `BackgroundTasks` after the POST has
    already responded.

    On success the result is also cached in the DECK's deck.json (`advice_cache`, keyed by the
    requested axis or "auto") so the Deck Mentor's `get_measured_swaps` can cite it (D2). The
    collection mtime is read BEFORE the search: a collection edited mid-run invalidates the
    entry rather than blessing a search that ran on the old file.
    """
    job = _jobs[advise_job_id]
    mtime = _suite_collection_mtime()
    try:
        result = _gauntlet_advise(commander, deck, axis=axis, themes=themes, partners=partners)
        if result is not None and "error" not in result and narrate:
            result = _narrate_suggestions(result, deck_job)
        if result is None:
            job.update(status="error", error=(
                "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
                "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'."
            ))
        elif "error" in result:
            job.update(status="error", error=result["error"])
        else:
            job.update(status="done", result=result)
            if deck_job_id:
                _persist_advice(deck_job_id, axis or "auto", {
                    "result": result,
                    "deck_hash": _advice_deck_hash(commander, deck, partners),
                    "collection_mtime": mtime,
                    "computed_at": _dt.now().isoformat(timespec="seconds"),
                })
    except Exception as e:
        traceback.print_exc()
        job.update(status="error", error=str(e))


@app.post("/api/deck/{job_id}/advise")
async def advise_deck(job_id: str, req: AdviseDeckRequest, background_tasks: BackgroundTasks, request: Request):
    """Start upgrade-advice from the user's collection for a FINISHED deck (suite C4).

    Every suggestion is a measured axis delta from MythGauntlet's ablation re-simulation,
    never popularity. Needs the strength API (:8020) and a Myth Suite collection export.

    **Runs in the background (2026-08-26) — this used to block on the whole simulation
    inside the POST.** The advisor's own default (`max_eval=16, cut_pool=6, runs=300`)
    was measured end to end at **583s** against a real 99-card deck with Myth Forge's own
    GPU services warm-but-idle (the ordinary state right after a build) — ~10x the "~60s
    warm" estimate in `advisor.advise`'s docstring, which was swept at a smaller
    `max_eval=10` and a 5x-lower `runs=60`. That is far past any synchronous HTTP timeout
    worth setting: covering it would mean holding a live browser connection AND a FastAPI
    worker thread for ten-plus minutes, and a busier machine or bigger deck can only make
    it longer. So the fix is not a bigger timeout number or a smaller `max_eval`/`cut_pool`
    (that would just trade advice quality for a still-dishonest wait) — it's the same
    start-a-job/poll-for-it shape `style_sample` already uses for its own long ComfyUI
    renders. The POST returns a job id immediately; poll
    `GET /api/deck/advise/{advise_job_id}` for the result.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip + _CHAT_RATE_LIMIT_KEY, _RATE_LIMIT_CHAT_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_CHAT_REQUESTS} requests per {_RATE_LIMIT_WINDOW}s")
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has no deck to advise on.")
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in cards
    ]
    advise_job_id = uuid.uuid4().hex[:16]
    _jobs[advise_job_id] = {"status": "running", "kind": "advise", "result": None,
                            "error": None, "created_at": time.time()}
    background_tasks.add_task(
        _run_advise_job, advise_job_id, commander, deck, req.axis,
        _deck_archetypes(job), _job_partners(job), req.narrate, job, job_id,
    )
    return {"job_id": advise_job_id}


@app.get("/api/deck/advise/{advise_job_id}")
async def advise_status(advise_job_id: str):
    j = _jobs.get(advise_job_id)
    if not j or j.get("kind") != "advise":
        raise HTTPException(404, "Advise job not found")
    if j.get("status") == "done":
        return {"status": "done", "result": j.get("result")}
    if j.get("status") == "error":
        return {"status": "error", "detail": j.get("error")}
    return {"status": "running"}


@app.get("/api/collection")
def get_collection(q: str = "", offset: int = 0, limit: int = 200,
                   colors: str = "", types: str = "", rarities: str = "", sets: str = "",
                   cmc_min: Optional[int] = None, cmc_max: Optional[int] = None,
                   min_count: Optional[int] = None, color_presence: str = "",
                   game_changers_only: bool = False,
                   sort: str = "name", direction: str = "asc",
                   then: str = "", then_direction: str = "asc", group: str = "none",
                   finishes: str = "", treatments: str = "", languages: str = "",
                   multi_printing: bool = False):
    """Owned cards, enriched with offline card metadata, filtered, sorted and paginated.

    The CSV stores only name/count/set/collector-number, so colour, type, mana value and
    rarity are joined in from the local card stores — no network. `colors`/`types`/
    `rarities`/`sets` are comma-separated; values within one are ORed, the criteria are
    ANDed. limit<=0 returns all matches (still capped at 5000 for safety).

    `color_presence` is `colors`' complement, not a duplicate: `colors=W` matches only
    mono-white rows (the CollectionStats "Colors" bar's exclusive bucket), while
    `color_presence=W` also matches a Boros card — "does this card have a white pip at
    all", the question CollectionStats' `color_presence` breakdown answers. See
    `collection_index.filter_rows`.
    """
    rows, enriched = _enriched_collection()
    matched = filter_rows(enriched, q=q, colors=_csv_param(colors), types=_csv_param(types),
                          rarities=_csv_param(rarities), sets=_csv_param(sets),
                          cmc_min=cmc_min, cmc_max=cmc_max, min_count=min_count,
                          color_presence=_csv_param(color_presence),
                          game_changers_only=game_changers_only,
                          finishes=_csv_param(finishes), treatments=_csv_param(treatments),
                          languages=_csv_param(languages), multi_printing=multi_printing)
    ordered = sort_rows(matched, sort, direction, then=then or None,
                        then_direction=then_direction)
    # Group the WHOLE filtered set, then paginate: the subtotals must not depend on where
    # a page (or the 5000 cap) cuts. An unknown `group` is "none".
    ordered, groups = group_rows(ordered, group if group in GROUP_BYS else "none")
    lim = 5000 if limit is None or limit <= 0 else min(limit, 5000)
    page = ordered[max(offset, 0): max(offset, 0) + lim]
    # Facets come from the WHOLE collection, not the filtered slice, so narrowing a
    # filter can never strand the user with no way back.
    return {"cards": page, "matched": len(matched), "groups": groups,
            "facets": coll_facets(enriched),
            **_collection_summary(rows, enriched=enriched)}


@app.get("/api/collection/stats")
def collection_stats_view(top_n: int = 10):
    """Value, colour spread, mana curve, type/rarity/set breakdown, most valuable cards."""
    _rows, enriched = _enriched_collection()
    return collection_stats(enriched, top_n=max(1, min(int(top_n), 50)))


@app.get("/api/collection/health")
def collection_health(limit: int = 300):
    """Rows whose NAME is really a whole decklist line, and what repairing them would do.

    Read-only: these are PROPOSALS. An older import parser stored lines like
    "13x Island (msh) 290 [Land]" verbatim as card names, and such a name matches nothing
    — so those cards are invisible to owned-aware building until they are repaired.
    """
    diag = coll_repair.diagnose(load_collection())
    shown = max(1, int(limit))
    return {**diag, "issues": diag["issues"][:shown],
            "shown": min(shown, diag["affected"]),
            "truncated": diag["affected"] > shown}


class CollectionRepairRequest(BaseModel):
    # Defaults to a dry run on purpose: this rewrites the canonical suite collection.
    dry_run: bool = True
    indexes: Optional[list[int]] = None   # issue indexes to accept; None = all of them


@app.post("/api/collection/repair")
def collection_repair_apply(req: CollectionRepairRequest):
    """Apply the repairs from /health. `dry_run` reports what WOULD change and writes
    nothing; a real run rewrites the CSV (leaving a .bak that /undo can restore)."""
    rows = load_collection()
    accept = set(req.indexes) if req.indexes is not None else None
    new_rows, report = coll_repair.apply_repairs(rows, accept)
    if not req.dry_run:
        coll_write(new_rows)
        rows = new_rows
    return {"dry_run": req.dry_run, **report, **_collection_summary(rows)}


@app.post("/api/collection/undo")
def collection_undo():
    """Restore the previous collection from the .bak every write leaves behind."""
    p = suite_collection_path()
    bak = p.with_suffix(p.suffix + ".bak")
    if not bak.exists():
        raise HTTPException(404, "No previous version to restore.")
    try:
        current, restored = (p.read_bytes() if p.exists() else b""), bak.read_bytes()
        # SWAP rather than overwrite, so Undo is itself undoable — press it twice and
        # you are back where you started. A plain restore would leave the .bak equal to
        # what we just wrote, stranding the newer version with no way to reach it.
        tmp = p.with_name(f".{p.name}.undo")
        tmp.write_bytes(restored)
        os.replace(tmp, p)          # atomic on the same volume, like write_collection
        bak.write_bytes(current)
    except OSError as e:
        logger.error("collection undo failed", exc_info=e)
        raise HTTPException(500, "Restore failed.")
    return {"restored": True, **_collection_summary(load_collection())}


_STALE_ROW = "Collection changed — reload."


class CollectionTarget(BaseModel):
    row_id: Optional[str] = None      # exact row (D6); wins over name/set/cn when present
    name: str = ""
    set:  str = ""
    cn:   str = ""


class CollectionBulkRequest(BaseModel):
    action:  str                      # "remove" | "set_count"
    targets: list[CollectionTarget]
    count:   int = 0                  # for set_count; <=0 removes


@app.post("/api/collection/bulk")
def collection_bulk(req: CollectionBulkRequest):
    """One action over many printings in a SINGLE write.

    Doing this a row at a time would rewrite the whole CSV per row and refresh the .bak
    each time — which quietly destroys Undo, since after the second write the backup is
    itself already-modified.
    """
    if req.action not in ("remove", "set_count"):
        raise HTTPException(400, "action must be 'remove' or 'set_count'.")
    if not req.targets:
        raise HTTPException(400, "No cards selected.")
    try:
        rows, affected = coll_bulk_apply([t.model_dump() for t in req.targets],
                                         req.action, int(req.count))
    except KeyError:
        raise HTTPException(409, _STALE_ROW)
    return {"affected": affected, "action": req.action, **_collection_summary(rows)}


class CollectionPrintingRequest(BaseModel):
    name:     str = ""
    set_code: str = ""
    cn:       str = ""
    from_set: Optional[str] = None    # which row to move; None = the first printing
    from_cn:  Optional[str] = None
    row_id:      Optional[str] = None  # exact row (D6); 409 when it no longer exists
    finish:      Optional[str] = None  # nonfoil | foil | etched; None keeps the row's finish
    scryfall_id: Optional[str] = None  # the chosen print; resolves set + cn from the store


def _print_for(name: str, set_code: str = "", cn: str = "", scryfall_id: str = "") -> dict | None:
    """The store's print for an id (authoritative, D2) or set + cn; None when the store
    is disabled/missing or has no such print."""
    if (scryfall_id or "").strip():
        hit = scryfall_prints.by_id(scryfall_id.strip())
        if hit:
            return hit
    return scryfall_prints.resolve(name, set_code, cn)


def _require_finish(print_: dict | None, finish: str) -> None:
    """400 when the store knows the print and it does not come in `finish`. A store that
    cannot answer cannot veto (the live fallback carries no finish data)."""
    finishes = (print_ or {}).get("finishes") or []
    if print_ and finishes and finish not in finishes:
        raise HTTPException(400, f"That printing is not available in {finish}.")


@app.patch("/api/collection/printing")
def collection_set_printing(req: CollectionPrintingRequest):
    """Point a row at a different printing (and finish) of the same card, keeping its count.

    This is how the rows whose printing is unknown get a real one without the user
    deleting and re-adding the card (which would lose the count). Merges into the target
    printing when the collection already holds it. With `row_id` the row is addressed
    exactly (409 when stale) and `finish` must be one the chosen print offers (400)."""
    rid = (req.row_id or "").strip()
    if rid:
        src = coll_find_by_id(load_collection(), rid)
        if src is None:
            raise HTTPException(409, _STALE_ROW)
        sid = (req.scryfall_id or "").strip()
        set_code = (req.set_code or "").strip().upper()
        cn = (req.cn or "").strip()
        name = (req.name or "").strip() or src["name"]
        if req.finish is not None:
            finish = coll_normalize_finish(req.finish)
        else:
            finish = coll_normalize_finish(src.get("finish", ""))
        if not sid and (set_code, cn) == ((src.get("set") or "").strip().upper(),
                                          (src.get("cn") or "").strip()):
            sid = (src.get("scryfall_id") or "").strip()   # finish-only change keeps the id
        print_ = _print_for(name, set_code, cn, sid)
        if print_:
            if owned_key(print_.get("name", "")) != owned_key(src["name"]):
                raise HTTPException(400, "That scryfall_id belongs to a different card.")
            set_code, cn, sid = print_["set"], print_["cn"], print_.get("id") or sid
        if not set_code:
            raise HTTPException(400, "A set code or scryfall_id is required.")
        _require_finish(print_, finish)
        try:
            rows = coll_set_printing_by_id(rid, set_code, cn, finish, sid)
        except KeyError:
            raise HTTPException(409, _STALE_ROW)
        return {"cards": rows[:200], **_collection_summary(rows)}
    if not (req.name or "").strip():
        raise HTTPException(400, "Card name is required.")
    if not (req.set_code or "").strip():
        raise HTTPException(400, "A set code is required.")
    rows = coll_set_printing(req.name.strip(), req.set_code, req.cn,
                             from_set=(req.from_set or None), from_cn=(req.from_cn or None))
    return {"cards": rows[:200], **_collection_summary(rows)}


@app.post("/api/collection/prices")
def collection_refresh_prices():
    """Refresh market prices for the whole collection from Scryfall and cache them.

    Batched 75 identifiers per request, so a ~750-card collection is ~10 calls. Rows
    with a known printing are priced as that printing; the rest by name."""
    rows = load_collection()
    if not rows:
        return {"priced": 0, "total_value": 0.0, **_collection_summary(rows)}
    try:
        prices = _scryfall.fetch_prices(rows)
    except Exception as e:
        logger.error("collection price refresh failed", exc_info=e)
        raise HTTPException(503, "Price lookup failed.")
    _save_prices({"updated": _dt.now().isoformat(timespec="seconds"), "prices": prices})
    # Resolved rows are priced from the per-printing store, so rebuild it too (R18). A failure
    # here must not undo the prices.json refresh above.
    try:
        scryfall_prints.refresh(force=True)
    except Exception as e:
        logger.error("prints store refresh failed during price refresh", exc_info=e)
    return _collection_summary(rows)


class CollectionAddRequest(BaseModel):
    name:     str
    count:    int = 1
    # Wire name stays "validate"; the attribute is renamed because it shadowed
    # BaseModel.validate and printed a warning on every server start.
    model_config = {"populate_by_name": True}
    validate_name: bool = Field(True, alias="validate")   # resolve the canonical Scryfall name first
    set_code: Optional[str] = None   # which printing; None -> default to the cheapest
    cn:       Optional[str] = None   # collector number (disambiguates within a set)
    finish:   str = "nonfoil"        # nonfoil | foil | etched (part of the row identity, D3)
    scryfall_id: Optional[str] = None  # the exact print; set + cn come from the store when it has it


def _cheapest_print(name: str, finish: str = "nonfoil", prints: list | None = None) -> tuple[str, str, str] | None:
    """(set, cn, scryfall_id) of the cheapest printing of `name` that offers `finish` and
    prices it (D8: another finish's price is never borrowed). Offline first; the live API
    only when the prints store knows nothing about the card. None when nothing is found."""
    if prints is None:
        prints = scryfall_prints.prints_of(name)
    if prints:
        best = None
        for p in prints:
            if finish not in (p.get("finishes") or []):
                continue
            price = coll_print_price(p, finish)
            if price is not None and (best is None or price < best[0]):
                best = (price, p)
        return (best[1]["set"], best[1]["cn"], best[1].get("id") or "") if best else None
    try:
        cheap = _scryfall.cheapest_printing(name)
    except Exception:
        cheap = None
    return (cheap["set"], cheap["collector_number"], "") if cheap else None


@app.post("/api/collection/add")
def collection_add(req: CollectionAddRequest):
    """Add copies of a card. When validate=True the name is resolved against Scryfall
    (fuzzy) so the stored spelling matches how decklists reference it; an unresolvable
    name is a 404 so the UI can warn instead of silently storing a typo."""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Card name is required.")
    display = name
    if req.validate_name:
        # Exact match first so a correctly-typed name is never fuzzed into a
        # different card (fuzzy turned "sol rng" into "Oathsworn Giant"); only fall
        # back to fuzzy when the exact spelling isn't found.
        card = None
        try:
            card = _scryfall.get_card_by_name(name, fuzzy=False)
        except Exception:
            card = None
        if not card or not card.get("name"):
            try:
                card = _scryfall.get_card_by_name(name, fuzzy=True)
            except Exception:
                card = None
        if not card or not card.get("name"):
            raise HTTPException(404, f"No card found matching '{name}'. Add it with validate=false to store as-is.")
        display = card["name"]

    finish = coll_normalize_finish(req.finish)
    sid = (req.scryfall_id or "").strip()
    set_code, cn = (req.set_code or "").strip().upper() or None, (req.cn or "").strip() or None
    # An id names the print exactly (D2): the store fills set + cn. With no store, what the
    # caller gave is stored as provided.
    print_ = _print_for(display, set_code or "", cn or "", sid) if (sid or set_code) else None
    if print_ and sid:
        if owned_key(print_.get("name", "")) != owned_key(display):
            raise HTTPException(400, "That scryfall_id belongs to a different card.")
        set_code, cn, sid = print_["set"], print_["cn"], print_.get("id") or sid
    _require_finish(print_, finish)
    # Printing: use what the caller gave us, else default to the CHEAPEST printing (of this
    # finish) so a collection entry always names a concrete, sensibly-priced version.
    if not set_code and not sid:     # an id the store doesn't know is stored exactly as given
        cheap = _cheapest_print(display, finish)
        if cheap:
            set_code, cn, sid = cheap[0], cheap[1], (cheap[2] or sid)
    rows = coll_add_card(name, max(int(req.count), 1), display_name=display,
                         set_code=set_code, cn=cn, finish=finish, scryfall_id=sid)
    return {"cards": rows[:200], "resolved_name": display, "set_code": set_code, "cn": cn,
            "finish": finish, "scryfall_id": sid, **_collection_summary(rows)}


def _owned_on_print(print_: dict, rows: list[dict], n_in_set: int) -> list[dict]:
    """The collection rows that ARE this printing: by scryfall id when the row has one (the
    id wins over a contradicting set, D2), else set + cn; a row with a set but no cn counts
    only when that set holds exactly one printing of the card."""
    out = []
    for r in rows:
        rsid = (r.get("scryfall_id") or "").strip().lower()
        if rsid:
            hit = rsid == str(print_.get("id") or "").lower()
        else:
            rset = (r.get("set") or "").strip().upper()
            rcn = (r.get("cn") or "").strip().casefold()
            if not rset or rset != print_.get("set"):
                hit = False
            elif rcn:
                hit = rcn == str(print_.get("cn") or "").casefold()
            else:
                hit = n_in_set == 1
        if hit:
            out.append({"row_id": coll_row_id(r), "finish": coll_normalize_finish(r.get("finish", "")),
                        "count": int(r.get("count", 0))})
    return out


def _usd_alias(prices: dict):
    """R12 `usd`: the nonfoil price, else the foil price, else None."""
    v = prices.get("nonfoil")
    return v if v is not None else prices.get("foil")


@app.get("/api/collection/printings")
def collection_printings(name: str):
    """Every printing of a card, newest first, for the printing picker. Offline from the
    prints store; the live Scryfall search only when the store has nothing. Each item
    carries `owned`: the collection rows sitting on that exact printing."""
    nm = (name or "").strip()
    if not nm:
        raise HTTPException(400, "name required")
    key = owned_key(nm)
    rows = [r for r in load_collection() if owned_key(r["name"]) == key]
    prints = scryfall_prints.prints_of(nm)
    if prints:
        per_set: dict[str, int] = {}
        for p in prints:
            per_set[p["set"]] = per_set.get(p["set"], 0) + 1
        items = []
        for p in prints:
            imgs = p.get("images") or {}
            prices_by_finish = {f: coll_print_price(p, f) for f in ("nonfoil", "foil", "etched")}
            items.append({
                "id": p.get("id"), "set": p["set"], "set_name": p.get("set_name"), "cn": p["cn"],
                "released_at": p.get("released_at"), "rarity": p.get("rarity"),
                "finishes": list(p.get("finishes") or []),
                "prices": prices_by_finish,
                "treatments": coll_treatments_of(p, "nonfoil"),
                "image": imgs.get("normal") or imgs.get("small") or "",
                "art_crop": imgs.get("art_crop") or "",
                "collector_number": p["cn"],      # R12: back-compat aliases for the old modal
                "usd": _usd_alias(prices_by_finish),
                "owned": _owned_on_print(p, rows, per_set[p["set"]]),
            })
        return {"printings": items}
    try:
        live = _scryfall.get_printings(nm)
    except Exception as e:
        logger.error("collection printings lookup failed for %r", nm, exc_info=e)
        raise HTTPException(503, "Scryfall lookup failed.")
    items = []
    for p in live[:60]:
        shim = {"id": None, "set": p.get("set", ""), "cn": p.get("collector_number", "")}
        items.append({
            "id": None, "set": shim["set"], "set_name": p.get("set_name") or None, "cn": shim["cn"],
            "released_at": None, "rarity": None, "finishes": [],
            "prices": {"nonfoil": p.get("usd"), "foil": None, "etched": None},
            "treatments": [], "image": p.get("image") or "", "art_crop": "",
            "collector_number": shim["cn"], "usd": p.get("usd"),
            "owned": _owned_on_print(shim, rows, 2),    # 2: a set-only row cannot be matched blind
        })
    return {"printings": items}


@app.get("/api/card-image")
def card_image(name: str):
    """Resolve a card NAME to its Scryfall image URLs (for hover previews).

    Exact-first then fuzzy, via the cached ScryfallClient. Handles double-faced cards
    (image_uris live on the front face). Returns {name, normal, art_crop} or 404."""
    nm = (name or "").strip()
    if not nm:
        raise HTTPException(400, "name required")
    card = None
    try:
        card = _scryfall.get_card_by_name(nm, fuzzy=False) or _scryfall.get_card_by_name(nm, fuzzy=True)
    except Exception:
        card = None
    if not card:
        raise HTTPException(404, f"no card matching '{nm}'")
    imgs = card.get("image_uris") or {}
    if not imgs:
        faces = card.get("card_faces") or []
        if faces and isinstance(faces[0], dict):
            imgs = faces[0].get("image_uris") or {}
    return {
        "name": card.get("name", nm),
        "normal": imgs.get("normal") or imgs.get("large") or imgs.get("small") or "",
        "art_crop": imgs.get("art_crop") or "",
    }


@app.get("/api/card-lookup")
def card_lookup(name: str):
    """Full card data by NAME, shaped for the Single Card form.

    Lets a user proxy a REAL card: look it up, prefill every field with the real
    printed values (rules text verbatim), then generate new art for it. Exact-first
    then fuzzy (guarded), so a near-miss resolves but a typo doesn't silently become
    a different card."""
    nm = (name or "").strip()
    if not nm:
        raise HTTPException(400, "name required")
    card = None
    try:
        card = _scryfall.get_card_by_name(nm, fuzzy=False) or _scryfall.get_card_by_name(nm, fuzzy=True)
    except Exception:
        card = None
    if not card:
        raise HTTPException(404, f"No card found matching '{nm}'")
    imgs = card.get("image_uris") or {}
    if not imgs:
        faces = card.get("card_faces") or []
        if faces and isinstance(faces[0], dict):
            imgs = faces[0].get("image_uris") or {}
    return {
        "name":        card.get("name", nm),
        "mana_cost":   card.get("mana_cost", "") or "",
        "type_line":   card.get("type_line", "") or "",
        "oracle_text": card.get("oracle_text", "") or "",
        "flavor_text": card.get("flavor_text", "") or "",
        "power":       card.get("power") or "",
        "toughness":   card.get("toughness") or "",
        "loyalty":     card.get("loyalty") or "",
        "rarity":      card.get("rarity", "") or "",
        "colors":      card.get("color_identity", []) or [],
        "image":       imgs.get("normal") or imgs.get("large") or "",
    }


@app.get("/api/collection/suggest")
def collection_suggest(q: str = ""):
    """Card-name typeahead for the add box (Scryfall autocomplete). Returns up to
    ~20 canonical names; empty list on short/blank query or any upstream hiccup."""
    ql = (q or "").strip()
    if len(ql) < 2:
        return {"suggestions": []}
    try:
        # Use the ScryfallClient's session — Scryfall rejects requests without a
        # proper User-Agent/Accept header (a bare requests.get returns nothing).
        r = _scryfall.session.get("https://api.scryfall.com/cards/autocomplete",
                                  params={"q": ql}, timeout=5)
        if r.status_code == 200:
            return {"suggestions": (r.json().get("data") or [])[:20]}
    except Exception:
        pass
    return {"suggestions": []}


class CollectionCountRequest(BaseModel):
    name:  str = ""
    count: int
    row_id:   Optional[str] = None   # exact row (D6); name is then not needed
    set_code: Optional[str] = None   # target one printing; None = first printing
    cn:       Optional[str] = None


@app.patch("/api/collection/count")
def collection_set_count(req: CollectionCountRequest):
    """Set a card's exact count (0 removes it). With row_id, targets exactly that row (409
    when it no longer exists); else with set_code, targets that printing."""
    if (req.row_id or "").strip():
        try:
            rows = coll_set_count_by_id(req.row_id.strip(), int(req.count))
        except KeyError:
            raise HTTPException(409, _STALE_ROW)
        return {"cards": rows[:200], **_collection_summary(rows)}
    if not (req.name or "").strip():
        raise HTTPException(400, "Card name is required.")
    rows = coll_set_count(req.name.strip(), int(req.count),
                          set_code=(req.set_code or None), cn=(req.cn or None))
    return {"cards": rows[:200], **_collection_summary(rows)}


@app.post("/api/collection/backfill-printings")
def collection_backfill_printings(limit: int = 1000):
    """Fill in printings without ever replacing one. Offline from the prints store.

    - A row with a scryfall_id or a set already NAMES its printing: it is only normalized
      (a blank set / collector number filled from that print), never replaced.
    - A row with no printing data at all gets the cheapest printing that offers its finish
      (D8: priced in that finish). The live API is used only for a card the store does not
      know. One write for the whole pass; rows that become identical merge (counts sum)."""
    rows = load_collection()
    filled = failed = normalized = 0
    cheapest: dict = {}
    prints_cache: dict = {}          # prints_of once per distinct name, across finishes
    seen = 0
    for r in rows:
        sid = (r.get("scryfall_id") or "").strip()
        rset = (r.get("set") or "").strip()
        rcn = (r.get("cn") or "").strip()
        if sid or rset:
            if sid and rset and rcn:
                continue
            p = _print_for(r["name"], rset, rcn, sid)
            if not p:
                continue
            changed = False
            if not rset:
                r["set"], changed = p["set"], True
            if not rcn and r["set"].strip().upper() == p["set"]:
                r["cn"], changed = p["cn"], True
            if changed:
                normalized += 1
            continue
        if seen >= max(1, int(limit)):
            continue
        seen += 1
        fin = coll_normalize_finish(r.get("finish", ""))
        ck = (owned_key(r["name"]), fin)
        if ck not in cheapest:
            nk = ck[0]
            if nk not in prints_cache:
                prints_cache[nk] = scryfall_prints.prints_of(r["name"])
            cheapest[ck] = _cheapest_print(r["name"], fin, prints_cache[nk])
        cheap = cheapest[ck]
        if cheap:
            r["set"], r["cn"] = cheap[0], cheap[1]
            if cheap[2]:
                r["scryfall_id"] = cheap[2]
            filled += 1
        else:
            failed += 1
    if filled or normalized:
        merged: list[dict] = []
        exact: dict = {}
        for r in rows:                      # a changed row may now equal another (D4)
            _coll_merge_row(merged, exact, None, r)
        rows = merged
        coll_write(rows)
    remaining = sum(1 for r in rows
                    if not (r.get("set") or "").strip() and not (r.get("scryfall_id") or "").strip())
    return {"filled": filled, "failed": failed, "normalized": normalized, "remaining": remaining,
            **_collection_summary(rows)}


@app.delete("/api/collection")
def collection_remove(name: str = "", set_code: str | None = None, cn: str | None = None,
                      row_id: str | None = None):
    """Remove a card entirely (matched on front-face name, case-insensitive).

    The name is a QUERY param, not a path segment: double-faced/split card names
    contain '//', and an encoded slash in the path 405s under Starlette routing.

    `row_id` removes exactly that row (409 when it no longer exists) and needs no name."""
    if (row_id or "").strip():
        try:
            rows = coll_remove_by_id(row_id.strip())
        except KeyError:
            raise HTTPException(409, _STALE_ROW)
        return {"cards": rows[:200], **_collection_summary(rows)}
    if not (name or "").strip():
        raise HTTPException(400, "Card name is required.")
    rows = coll_remove_card(name, set_code=(set_code or None), cn=(cn or None))
    return {"cards": rows[:200], **_collection_summary(rows)}


class CollectionImportRequest(BaseModel):
    text: str
    mode: str = "merge"   # "merge" adds onto the current collection; "replace" overwrites


@app.post("/api/collection/import")
def collection_import(req: CollectionImportRequest):
    """Bulk-import a pasted Moxfield CSV or a plain decklist. No Scryfall validation
    (imports can be large); names are stored as written and normalized on read."""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "Nothing to import.")
    mode = "replace" if req.mode == "replace" else "merge"
    rows = coll_bulk_import(text, mode=mode)
    return {"cards": rows[:200], "imported_mode": mode, **_collection_summary(rows)}


# Cache the buildable scan keyed on the collection file's mtime, so repeat views are
# instant and any edit (which rewrites the CSV) transparently invalidates it.
_buildable_cache: dict = {"key": None, "data": None}


@app.get("/api/collection/buildable")
def collection_buildable(limit: int = 8):
    """Which commanders you own could you build a B1-3 deck from, ranked by how
    complete each deck would be. Fast local scan (no simulation); 'Build this' then
    goes through the normal generate flow where the deck can be measured."""
    import buildable
    p = suite_collection_path()
    mtime = p.stat().st_mtime if p.exists() else 0
    key = (mtime, int(limit))
    if _buildable_cache["key"] == key and _buildable_cache["data"] is not None:
        return {**_buildable_cache["data"], "cached": True}
    owned = load_owned_names()
    try:
        data = buildable.find_buildable(owned, _scryfall, limit=int(limit))
    except Exception as e:
        logger.error("buildable collection scan failed", exc_info=e)
        raise HTTPException(503, "Could not scan the collection (Scryfall).")
    _buildable_cache.update({"key": key, "data": data})
    return {**data, "cached": False}


@app.post("/api/deck/{job_id}/measure")
def measure_deck(job_id: str):
    """Simulation-grounded strength for a FINISHED deck (suite C3, result screen).

    Converts the stored deck.json back into a decklist and reuses the same
    MythGauntlet call as import-preview, so imported and generated decks measure
    identically. 503 when the strength API is down (the UI says how to start it);
    400 for a single-card build (nothing to measure).
    """
    _require_job_id(job_id)
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has no deck to measure.")
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in cards
    ]
    sim = _gauntlet_analyze(commander, deck, partners=_job_partners(job))
    if sim is None:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        )
    # Persist the measurement so History/Recent tiles can badge the measured
    # bracket and the result screen shows the cached profile without re-simulating.
    stamp = {"simulation": sim, "date": _dt.now().isoformat(timespec="seconds")}
    try:
        p = state.RENDER_DIR / job_id / "deck.json"
        if p.exists():
            disk_data = json.loads(p.read_text(encoding="utf-8"))
            disk_data["last_measure"] = stamp
            p.write_text(json.dumps(disk_data), encoding="utf-8")
        if job_id in _jobs:
            _jobs[job_id]["last_measure"] = stamp
    except Exception as e:
        print(f"  [measure] could not persist last_measure: {e}")
    return sim


class ApplySwapRequest(BaseModel):
    add: str
    cut: str


@app.post("/api/deck/{job_id}/apply-swap")
def apply_swap(job_id: str, req: ApplySwapRequest):
    """Apply an advisor suggestion to a FINISHED deck: cut one card, add another.

    Closes the build -> test -> improve loop (suite C4): the AdvisePanel's measured
    suggestions become one-click edits instead of a manual re-import. The added card
    is stored UNTHEMED (real name, Scryfall art fallback, swapped_in flag) — theming
    art for it is a later regen, not a blocker for testing. The cached measurement is
    invalidated because the deck changed; the swap is recorded in applied_swaps.
    """
    _require_job_id(job_id)
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        _jobs[job_id] = disk
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has no deck to modify.")

    cut_norm = req.cut.strip().casefold()
    idx = next(
        (i for i, c in enumerate(cards)
         if (c.get("original_name") or "").casefold() == cut_norm),
        None,
    )
    if idx is None:
        raise HTTPException(400, f"'{req.cut}' is not in this deck (already swapped out?)")
    add_norm = req.add.strip().casefold()
    if any((c.get("original_name") or "").casefold() == add_norm for c in cards):
        raise HTTPException(400, f"'{req.add}' is already in this deck.")

    card = _scryfall.get_card_by_name(req.add, fuzzy=True)
    if not card:
        raise HTTPException(400, f"Card not found on Scryfall: {req.add}")

    # cut: decrement a stack (imported duplicate basics), else remove the entry
    if (cards[idx].get("quantity") or 1) > 1:
        cards[idx]["quantity"] = cards[idx]["quantity"] - 1
    else:
        cards.pop(idx)

    swap_no = int(job.get("swap_count") or 0) + 1
    job["swap_count"] = swap_no
    name = card.get("_front_name") or card.get("name") or req.add
    new_entry = {
        "original_name": name,
        "themed_name":   name,               # unthemed — shows the real card
        "art_prompt":    "",
        "custom_prompt": "",
        "use_custom":    False,
        "flavor_text":   "",
        "mana_cost":     card.get("mana_cost", ""),
        "type_line":          card.get("type_line", ""),
        "original_type_line": card.get("type_line", ""),
        "oracle_text":   card.get("oracle_text", ""),
        "cmc":           card.get("cmc", 0),
        "colors":        card.get("color_identity", []),
        "power":         card.get("power"),
        "toughness":     card.get("toughness"),
        "rarity":        card.get("rarity", ""),
        "quantity":      1,
        "scryfall_img":  (card.get("image_uris") or {}).get("normal", ""),
        "has_render":    False,              # tile falls back to scryfall_img
        "has_video":     False,
        "render_key":    f"{_safe_name(name)}_swap{swap_no:02d}",
        "swapped_in":    True,               # UI badge: an applied upgrade
    }
    cards.insert(min(idx, len(cards)), new_entry)

    swap_record = {"add": name, "cut": req.cut,
                   "date": _dt.now().isoformat(timespec="seconds")}
    job.setdefault("applied_swaps", []).append(swap_record)
    job.pop("last_measure", None)            # the measurement no longer matches the list

    try:
        p = state.RENDER_DIR / job_id / "deck.json"
        if p.exists():
            disk_data = json.loads(p.read_text(encoding="utf-8"))
            disk_data["deck"] = cards
            disk_data["swap_count"] = swap_no
            disk_data.setdefault("applied_swaps", []).append(swap_record)
            disk_data.pop("last_measure", None)
            p.write_text(json.dumps(disk_data), encoding="utf-8")
    except Exception as e:
        print(f"  [apply-swap] could not persist swap: {e}")

    return _serializable_job(job)


class DuelRequest(BaseModel):
    opponent: str                 # opponent decklist text (pasted, Moxfield/plain)
    opponent_name: str = "Opponent"
    games: int = 120


def _gauntlet_duel(commander, deck, opponent_text, name_a, name_b, games, partners=None):
    """Head-to-head win rate from MythGauntlet's Tier-2 adversarial engine.

    Returns the duel JSON, {"error": detail} for a meaningful 400 (unparseable
    opponent list), or None when the service is unreachable.
    """
    try:
        payload = {
            "deck_a": _deck_to_lines(commander, deck, partners),
            "deck_b": opponent_text,
            "name_a": name_a or "Your deck",
            "name_b": name_b or "Opponent",
            "games": max(20, min(400, int(games))),
            "seed": 42,
        }
        resp = requests.post(f"{MYTHGAUNTLET_URL}/duel", json=payload, timeout=180)
        if resp.status_code == 400:
            try:
                return {"error": resp.json().get("detail", "duel failed")}
            except Exception:
                return {"error": "duel failed"}
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"  [duel] MythGauntlet strength API unavailable: {e}")
        return None


@app.post("/api/deck/{job_id}/duel")
def duel_deck(job_id: str, req: DuelRequest):
    """Test THIS finished deck head-to-head against a pasted opponent decklist (Tier-2).

    Battlecruiser-fidelity 1v1 win rate — an honest "how does my deck play against
    my friend's?" read, not a bracket verdict. Needs the strength API (:8020).
    """
    _require_job_id(job_id)
    if not (req.opponent or "").strip():
        raise HTTPException(400, "Paste an opponent decklist to test against.")
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has nothing to duel with.")
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in cards
    ]
    name_a = (job.get("commander") or {}).get("themed_name") \
        or (job.get("commander") or {}).get("original_name") or "Your deck"
    result = _gauntlet_duel(
        commander, deck, req.opponent, name_a, req.opponent_name, req.games,
        partners=_job_partners(job),
    )
    if result is None:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/api/deck/import-preview")
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


@app.post("/api/deck/import-save")
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


@app.post("/api/commander/search")
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


@app.get("/api/commander/autocomplete")
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


@app.get("/api/deck/active")
async def get_active_job():
    """Return the most-recent in-memory building job so a refresh can reconnect.
    Does NOT fall back to disk — that auto-loaded random old decks on first visit."""
    building = [(jid, j) for jid, j in _jobs.items() if j.get("status") == "building"]
    if building:
        jid, _ = building[-1]
        return {"job_id": jid, "status": "building"}
    return {"job_id": None, "status": "none"}


@app.get("/api/decks")
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


@app.get("/api/playstyles")
async def get_playstyles():
    return [
        {"key": k, "label": PLAYSTYLES[k]["label"], "description": PLAYSTYLES[k]["description"]}
        for k in PLAYSTYLE_ORDER
    ]


class GenerateListRequest(BaseModel):
    commander_name: str = Field("", max_length=120)
    partner_names:  list[str] = Field(default_factory=list, max_length=2)
    playstyle:      str = "auto"
    bracket:        int = 3
    use_collection: bool = False   # prefer owned cards (Myth Suite C4)
    card_source:    str = Field("", max_length=24)   # see _resolve_card_source


@app.post("/api/deck/generate-list")
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


@app.post("/api/deck/theme-preview")
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
    from themer import (build_creative_brief, verify_motif_coverage,
                        build_color_factions, _deck_color_identity,
                        _generate_style_guide as _gen_style_guide,
                        OLLAMA_MODEL as _DEF_MODEL, LLM_CATALOG as _CATALOG)
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


@app.post("/api/deck/style-sample")
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


@app.get("/api/deck/style-sample/{job_id}")
async def style_sample_status(job_id: str):
    j = _jobs.get(job_id)
    if not j or j.get("kind") != "style_sample":
        raise HTTPException(404, "Sample job not found")
    return {"status": j.get("status"), "error": j.get("error"),
            "current": j.get("current"), "total": j.get("total"),
            "images": j.get("images", [])}


@app.get("/api/deck/style-sample/{job_id}/img/{idx}")
async def style_sample_image(job_id: str, idx: int):
    _require_job_id(job_id)
    path = _STYLE_SAMPLE_DIR / job_id / f"sample_{idx}.png"
    if not path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(path, media_type="image/png")


@app.post("/api/deck/build")
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


@app.post("/api/card/build")
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


@app.post("/api/deck/{job_id}/cancel")
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


@app.post("/api/deck/{job_id}/rebuild")
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


@app.post("/api/deck/{job_id}/regen-cards")
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


@app.get("/api/video-health")
def video_health():
    """Whether an image-to-video model is installed + ready (gates the UI)."""
    import card_video
    return card_video.health_check()


@app.get("/api/video-presets")
def video_presets():
    """Motion presets, foil styles and output formats for the Animate panel."""
    import card_video
    return {"presets": card_video.motion_presets(),
            "foil_styles": card_video.foil_styles(),
            "formats": card_video.format_options(),
            "loop_styles": card_video.loop_styles(),
            "caps": card_video.video_caps()}


@app.post("/api/deck/{job_id}/animate-cards")
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


@app.post("/api/deck/{job_id}/retheme")
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


@app.post("/api/deck/{job_id}/duplicate")
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


@app.delete("/api/deck/{job_id}")
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


@app.post("/api/decks/delete-batch")
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


@app.get("/api/deck/{job_id}/events")
async def deck_events(job_id: str, request: Request):
    _require_job_id(job_id)
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")
    return StreamingResponse(
        _sse_stream(job_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/deck/{job_id}/status")
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


@app.get("/api/deck/{job_id}")
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


@app.get("/api/deck/{job_id}/card-image/{render_key}")
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


@app.get("/api/deck/{job_id}/card-video/{render_key}")
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


@app.get("/api/deck/{job_id}/set-symbol")
async def set_symbol_endpoint(job_id: str):
    _require_job_id(job_id)
    path = state.RENDER_DIR / job_id / "set_symbol.png"
    if not path.exists():
        raise HTTPException(404, "Set symbol not found")
    return FileResponse(path, media_type="image/png")


# ── Face upload ───────────────────────────────────────────────────────────────

# ── Capability probe cache ─────────────────────────────────────────────────────
# /api/face-method is called on every step-mount by the UI, but each call
# triggers 5+ HTTP requests to ComfyUI. Cache results for a short window.
_probe_cache: dict = {"ts": 0, "data": None}
_PROBE_TTL = 8.0   # seconds


@app.get("/api/face-method")
def face_method():
    """Probe face-conditioning engine and available checkpoints (cached ~8s)."""
    now = time.time()
    if _probe_cache["data"] and (now - _probe_cache["ts"]) < _PROBE_TTL:
        return _probe_cache["data"]

    # Check ComfyUI reachability before doing the expensive probe
    try:
        requests.get("http://127.0.0.1:8188/system_stats", timeout=3)
    except Exception:
        result = {"face_method": "not available", "available": False,
                  "comfyui_offline": True, "has_schnell": False, "has_dev": False}
        _probe_cache.update({"ts": now, "data": result})
        return result

    try:
        # Single ImageGen() call handles both checkpoint detection and face
        # method setup. We avoid the duplicate list_checkpoints() HTTP roundtrip.
        ckpts = ImageGen.list_checkpoints()
        gen   = ImageGen()
        result = {
            "face_method":     gen.face_method_label,
            "available":       gen.face_method != "none",
            "comfyui_offline": False,
            "has_schnell":     len(ckpts["schnell"]) > 0,
            "has_dev":         len(ckpts["dev"]) > 0,
            "checkpoints":     ckpts,
        }
        _probe_cache.update({"ts": now, "data": result})
        return result
    except Exception as e:
        return {"face_method": "not available", "available": False,
                "comfyui_offline": False, "has_schnell": False, "has_dev": False,
                "error": str(e)}


@app.get("/api/comfy-status")
def comfy_status():
    """
    Lightweight ComfyUI readiness probe for the UI.  Returns the same dict
    shape used by the build pre-flight so the frontend can warn the user
    before they kick off a long build that would otherwise fall back to
    Scryfall art on every card.
    """
    return ImageGen.health_check()


@app.get("/api/health")
def health_check():
    """
    System health check: returns status of ComfyUI and Ollama services.
    Used by the frontend status indicator in the corner.
    """
    from themer import LLM_BACKEND, installed_models

    comfyui_status = "up"

    # Check ComfyUI
    try:
        r = requests.get("http://127.0.0.1:8188/system_stats", timeout=2)
        if r.status_code != 200:
            comfyui_status = "down"
    except Exception:
        comfyui_status = "down"

    # Check the LLM backend (llama.cpp via llama-swap, or Ollama)
    llm_status = "up" if installed_models(timeout=2) else "down"

    return {
        "comfyui": comfyui_status,
        # `ollama` key retained for backward compat; `llm` is the current key.
        "ollama": llm_status,
        "llm": llm_status,
        "llm_backend": LLM_BACKEND,
        "timestamp": time.time()
    }


@app.get("/api/llm-models")
def get_llm_models():
    """
    Return the curated LLM catalog with per-entry installed status.
    The UI uses this to populate the model selector in StepTheme.
    Entries flagged installed=False are shown disabled with a pull hint.
    """
    from themer import list_available_llms
    return list_available_llms()


@app.get("/api/frame-styles")
def get_frame_styles():
    """Frame systems the UI can offer. 'builtin' is always available; 'm15'
    requires a local Card Conjurer install (MYTHFORGE_CC_DIR) with M15 assets."""
    try:
        import cc_frames
        m15_ok = cc_frames.is_available("m15")
        fullart_ok = cc_frames.is_available("m15_fullart")
        extended_ok = cc_frames.is_available("m15_extended")
    except Exception:
        m15_ok = fullart_ok = extended_ok = False
    cc_hint = "Install Card Conjurer locally and set MYTHFORGE_CC_DIR to enable."
    return {
        "styles": [
            {"key": "builtin", "label": "Built-in Frames", "available": True,
             "note": "Bundled proxy frames — always available."},
            {"key": "m15", "label": "Official-style (M15)", "available": m15_ok,
             "note": ("Modern frames rendered from your local Card Conjurer install."
                      if m15_ok else cc_hint)},
            {"key": "m15_extended", "label": "Extended-art (M15)", "available": extended_ok,
             "note": ("Full-width extended art with a normal text box, from your local Card Conjurer."
                      if extended_ok else cc_hint)},
            {"key": "m15_fullart", "label": "Full-art (Borderless)", "available": fullart_ok,
             "note": ("Edge-to-edge full-art borderless frames from your local Card Conjurer."
                      if fullart_ok else cc_hint)},
        ],
        "default": "builtin",
    }


class FrameConfigRequest(BaseModel):
    cc_dir: str = Field("", max_length=600)


@app.get("/api/frame-config")
def get_frame_config():
    """Current Card Conjurer folder setting (for the in-app configuration field)."""
    try:
        import cc_frames
        return {
            "cc_dir":   cc_frames.configured_cc_dir(),
            "from_env": bool(os.environ.get("MYTHFORGE_CC_DIR", "").strip()),
            "valid":    cc_frames.cc_root() is not None,
        }
    except Exception as e:
        return {"cc_dir": "", "from_env": False, "valid": False, "error": str(e)}


@app.post("/api/frame-config")
def set_frame_config(req: FrameConfigRequest):
    """Set the Card Conjurer folder from the UI. Persists to cc_config.json.
    The MYTHFORGE_CC_DIR env var (if set) always takes precedence over this."""
    import cc_frames
    if os.environ.get("MYTHFORGE_CC_DIR", "").strip():
        return {
            "ok": False,
            "error": "The MYTHFORGE_CC_DIR environment variable is set and overrides this setting. Unset it to configure the folder here.",
            "cc_dir": cc_frames.configured_cc_dir(),
            "valid": cc_frames.cc_root() is not None,
        }
    path = (req.cc_dir or "").strip()
    cc_frames.set_cc_dir(path)
    root = cc_frames.cc_root()
    valid = root is not None
    return {
        "ok": True,
        "cc_dir": cc_frames.configured_cc_dir(),
        "valid": valid,
        "m15":         cc_frames.is_available("m15"),
        "m15_fullart": cc_frames.is_available("m15_fullart"),
        "note": ("" if valid or not path else
                 "Folder set, but no img/frames found there — check the path points to your Card Conjurer root."),
    }


@app.get("/api/art-styles")
def get_art_styles():
    """
    Return all LoRA presets with per-LoRA install status.
    The UI uses this to show ready/missing badges and download hints.
    """
    from image_gen import get_all_presets

    # Query ComfyUI for installed LoRAs (tolerate ComfyUI being offline)
    installed_lower: list[str] = []
    try:
        r = requests.get("http://127.0.0.1:8188/object_info/LoraLoader", timeout=5)
        if r.status_code == 200:
            raw = (r.json()
                   .get("LoraLoader", {})
                   .get("input", {}).get("required", {})
                   .get("lora_name", [[]])[0])
            installed_lower = [f.lower() for f in raw]
    except Exception:
        pass

    from image_gen import _load_custom_presets
    custom_keys = set(_load_custom_presets().keys())

    result = []
    for key, preset in get_all_presets().items():
        loras = []
        for entry in preset["loras"]:
            frags = entry.get("fragments", [entry.get("fragment", "")])
            is_inst = any(
                any(frag.lower() in f for frag in frags)
                for f in installed_lower
            )
            loras.append({
                "label":         entry["label"],
                "installed":     is_inst,
                "download_url":  entry.get("download_url"),
                "download_note": entry.get("download_note"),
            })
        all_inst = all(l["installed"] for l in loras)
        any_inst = any(l["installed"] for l in loras)

        # Style variants (per-card rotation stacks) — surfaced so the UI can show a
        # "flavor" selector. Each variant is ready only when ALL its LoRAs are
        # installed; "Variety mix" (auto) is added client-side as the default.
        variants = []
        for stack in preset.get("lora_rotation", []) or []:
            v_loras = stack.get("loras", [])
            v_status = []
            for entry in v_loras:
                frags = entry.get("fragments", [entry.get("fragment", "")])
                v_status.append(any(
                    any(frag.lower() in f for frag in frags)
                    for f in installed_lower
                ))
            variants.append({
                "label":       stack.get("label", "Variant"),
                "description": stack.get("description", ""),
                "ready":       bool(v_status) and all(v_status),
                "partial":     any(v_status) and not all(v_status),
            })

        result.append({
            "key":         key,
            "label":       preset["label"],
            "description": preset["description"],
            "icon":        preset["icon"],
            "ready":       all_inst,
            "partial":     any_inst and not all_inst,
            "loras":       loras,
            "variants":    variants,
            "custom":      key in custom_keys,
            # Model type constraint — tells the UI which checkpoint family is required
            "required_checkpoint_type": preset.get("required_checkpoint_type"),
            # Include full config so the UI can pre-populate the editor
            "flux_prefix":      preset.get("flux_prefix") or "",
            "negative_prompt":  preset.get("negative_prompt", ""),
            "style_guide_hint": preset.get("style_guide_hint", ""),
            "themer_medium":    preset.get("themer_medium", ""),
            "themer_quality":   preset.get("themer_quality", ""),
        })
    return result


@app.get("/api/checkpoints")
def get_checkpoints():
    """
    Return all available checkpoints in ComfyUI.
    Enables UI dropdown for explicit checkpoint selection.
    """
    try:
        r = requests.get("http://127.0.0.1:8188/object_info/CheckpointLoaderSimple", timeout=5)
        if r.status_code == 200:
            ckpts = (
                r.json()
                .get("CheckpointLoaderSimple", {})
                .get("input", {}).get("required", {})
                .get("ckpt_name", [[]])[0]
            )
            # Filter out LTX and unconfirmed models
            usable = [c for c in ckpts if not c.startswith("LTX") and not c.startswith("Unconfirmed")]

            # Categorize by type using the same detection functions as image_gen.py
            result = []
            for ckpt in sorted(usable):
                if _is_krea(ckpt):
                    ckpt_type = "FLUX Krea"      # flux-dev arch → all FLUX LoRAs apply
                elif _is_flux(ckpt):
                    ckpt_type = "FLUX"
                elif _is_sd35(ckpt):
                    ckpt_type = "SD 3.5"
                elif _is_sdxl(ckpt):
                    ckpt_type = "SDXL"
                else:
                    ckpt_type = "Unknown"

                result.append({
                    "filename": ckpt,
                    "type": ckpt_type,
                    "label": f"{ckpt} ({ckpt_type})"
                })

            # Qwen-Image and FLUX.1-Krea-dev ship as UNET files (diffusion_models),
            # not CheckpointLoaderSimple checkpoints, so they never appear above. Probe
            # UNETLoader and add synthetic entries so the UI can offer them. Only the
            # first of each family is added (the app resolves companions by fragment).
            try:
                ur = requests.get("http://127.0.0.1:8188/object_info/UNETLoader", timeout=5)
                if ur.status_code == 200:
                    unets = (ur.json().get("UNETLoader", {}).get("input", {})
                             .get("required", {}).get("unet_name", [[]])[0]) or []
                    seen_qwen = seen_krea = False
                    for u in sorted(unets):
                        if u.startswith("Unconfirmed"):
                            continue
                        if _is_qwen(u) and not seen_qwen:
                            result.append({"filename": u, "type": "Qwen-Image",
                                           "label": f"{u} (Qwen-Image)"})
                            seen_qwen = True
                        elif _is_krea(u) and not seen_krea:
                            result.append({"filename": u, "type": "FLUX Krea",
                                           "label": f"{u} (FLUX Krea)"})
                            seen_krea = True
            except Exception:
                pass
            return result
    except Exception:
        pass

    return []


@app.get("/api/comfyui/loras")
def list_comfyui_loras():
    """
    Return all LoRA filenames currently installed in ComfyUI.
    Used by the custom-style builder so the user can pick from installed LoRAs.
    """
    try:
        r = requests.get("http://127.0.0.1:8188/object_info/LoraLoader", timeout=5)
        if r.status_code == 200:
            raw = (r.json()
                   .get("LoraLoader", {})
                   .get("input", {}).get("required", {})
                   .get("lora_name", [[]])[0])
            return {"loras": raw, "online": True}
    except Exception:
        pass
    return {"loras": [], "online": False}


@app.post("/api/art-styles/custom")
async def upsert_custom_art_style(payload: dict):
    """
    Create or update a custom art style preset.

    Body shape (all fields except key/label/loras are optional):
    {
      "key":             "my_style",          # slug, no spaces
      "label":           "My Style",
      "description":     "...",
      "icon":            "✨",
      "flux_prefix":     "...",
      "negative_prompt": "...",               # optional
      "style_guide_hint": "...",
      "themer_medium":   '"illustration," or "painting,"',
      "themer_quality":  '"vivid colors" or "detailed"',
      "loras": [
        {
          "fragments":      ["filename_fragment"],
          "trigger":        "trigger word",
          "model_strength": 0.7,
          "clip_strength":  0.7,
          "dark_only":      false,
          "label":          "LoRA Name",
          "download_url":   null,
          "download_note":  ""
        }
      ]
    }
    """
    from image_gen import upsert_custom_preset

    key = payload.get("key", "").strip().replace(" ", "_")
    if not key:
        raise HTTPException(400, "key is required")

    # Guard against overwriting built-in presets
    from image_gen import _LORA_PRESETS
    if key in _LORA_PRESETS:
        raise HTTPException(400, f"'{key}' is a built-in preset and cannot be overwritten. Choose a different key.")

    preset = {
        "label":            payload.get("label", key),
        "description":      payload.get("description", ""),
        "icon":             payload.get("icon", "✨"),
        "flux_prefix":      payload.get("flux_prefix") or None,
        "style_guide_hint": payload.get("style_guide_hint", ""),
        "themer_medium":    payload.get("themer_medium", '"digital painting," or "illustration,"'),
        "themer_quality":   payload.get("themer_quality", '"vivid colors, detailed"'),
        "loras":            payload.get("loras", []),
    }
    # Only include negative_prompt if provided (avoids overriding default _FLUX_NEGATIVE for styles that don't need it)
    if payload.get("negative_prompt"):
        preset["negative_prompt"] = payload["negative_prompt"]

    # Report the truth: _save_custom_presets used to swallow write failures, so this
    # returned ok:True for a style that never reached disk and vanished on reload.
    try:
        upsert_custom_preset(key, preset)
    except OSError as e:
        logger.error("could not save custom art style %r", key, exc_info=e)
        raise HTTPException(500, f"Could not save custom art style '{key}'.") from e
    return {"ok": True, "key": key}


@app.delete("/api/art-styles/custom/{key}")
async def delete_custom_art_style(key: str):
    """Remove a custom art style preset."""
    from image_gen import delete_custom_preset, _LORA_PRESETS
    if key in _LORA_PRESETS:
        raise HTTPException(400, f"'{key}' is a built-in preset and cannot be deleted.")
    try:
        deleted = delete_custom_preset(key)
    except OSError as e:
        logger.error("could not delete custom art style %r", key, exc_info=e)
        raise HTTPException(500, f"Could not delete custom art style '{key}'.") from e
    if not deleted:
        raise HTTPException(404, f"Custom preset '{key}' not found.")
    return {"ok": True, "key": key}


@app.post("/api/upload-face")
async def upload_face(files: List[UploadFile] = File(...)):
    """
    Accept 1-15 face reference photos (commander group: up to 5; crew group: up to 10).
    Returns a face_key that the client includes in the BuildRequest so the
    art generator can apply the user's likeness to humanoid card art.
    """
    if not files:
        raise HTTPException(400, "No files provided")
    if len(files) > 15:
        raise HTTPException(400, f"Maximum 15 photos per upload group ({len(files)} received)")

    MAX_PER_FILE = 20 * 1024 * 1024   # 20 MB per image
    MAX_TOTAL    = 60 * 1024 * 1024   # 60 MB total across the upload

    face_key  = uuid.uuid4().hex[:16]
    file_list: list[tuple[str, bytes]] = []
    total_bytes = 0
    for f in files:
        data = await f.read()
        if not data:
            raise HTTPException(400, f"File '{f.filename}' is empty")
        if len(data) > MAX_PER_FILE:
            raise HTTPException(413, f"File '{f.filename}' exceeds 20 MB limit")
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL:
            raise HTTPException(413, f"Total upload exceeds {MAX_TOTAL // (1024*1024)} MB")
        # Hard magic-byte check — reject anything that isn't a real image header.
        is_jpeg = data[:3] == b'\xff\xd8\xff'
        is_png  = data[:8] == b'\x89PNG\r\n\x1a\n'
        is_webp = data[:4] == b'RIFF' and data[8:12] == b'WEBP'
        is_gif  = data[:4] == b'GIF8'
        if not (is_jpeg or is_png or is_webp or is_gif):
            raise HTTPException(400, f"File '{f.filename}': not a recognized image (JPEG/PNG/WebP/GIF only)")
        # Defense in depth: ask PIL to verify the body is a parseable image.
        try:
            from PIL import Image as _PILImg
            _img = _PILImg.open(io.BytesIO(data))
            _img.verify()
        except Exception as _ve:
            raise HTTPException(400, f"File '{f.filename}': image data corrupt or unsupported ({_ve})")
        file_list.append((f.filename or "photo.jpg", data))

    from face_ref import save_face_images
    paths = save_face_images(file_list, face_key)

    # Probe which face method ImageGen will use — reuse cached probe if fresh
    # to avoid a 5-roundtrip ComfyUI hit on every face upload.
    method_label = "unknown"
    now = time.time()
    if _probe_cache["data"] and (now - _probe_cache["ts"]) < _PROBE_TTL:
        method_label = _probe_cache["data"].get("face_method", "unknown")
    else:
        try:
            gen = ImageGen()
            method_label = gen.face_method_label
        except Exception:
            pass

    return {
        "face_key":     face_key,
        "count":        len(paths),
        "face_method":  method_label,
    }


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


@app.get("/api/deck/{job_id}/export/zip")
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
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="{safe}_{"card" if single else "deck"}.zip"'},
    )


@app.get("/api/deck/{job_id}/export/decklist")
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
    return StreamingResponse(
        io.BytesIO(body.encode("utf-8")),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}_decklist.txt"'},
    )


@app.get("/api/deck/{job_id}/export/videos")
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
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}_videos.zip"'},
    )


@app.get("/api/deck/{job_id}/export/pdf")
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
    return StreamingResponse(
        io.BytesIO(data),
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


@app.post("/api/deck/{job_id}/generate-3d")
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
    health = Model3DGen.health_check()
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


@app.get("/api/deck/{job_id}/3d-status/{job_3d_id}")
async def stream_3d_status(job_id: str, job_3d_id: str, request: Request):
    """SSE stream for 3D generation progress."""
    _require_job_id(job_id)
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


@app.get("/api/deck/{job_id}/commander-3d.stl")
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


@app.get("/api/3d-health")
async def get_3d_health():
    """Return Hunyuan3D v2 / rembg availability status."""
    return JSONResponse(Model3DGen.health_check())


@app.get("/api/logs")
async def get_logs(lines: int = 300):
    """
    Return the most recent server log lines from the in-memory ring buffer.
    Captures stdout/stderr (startup checks, pipeline prints, tracebacks) and
    uvicorn access logs. `lines` is clamped to [1, 5000].
    """
    lines = max(1, min(int(lines), 5000))
    buf = list(_LOG_BUFFER)
    recent = buf[-lines:]
    return JSONResponse({
        "lines":    recent,
        "total":    len(buf),
        "returned": len(recent),
    })


# ── Serve React frontend ───────────────────────────────────────────────────────
if state.STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=state.STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        index = state.STATIC_DIR / "index.html"
        return FileResponse(index)


# Service lifecycle (ComfyUI + LLM backend) lives in services.py — see that module's
# docstring. Only three names are needed here; the progress callback is registered below.
from services import (  # noqa: E402  (after app/_push are defined)
    _ensure_comfyui_ready,
    _start_comfyui,
    _start_llm_backend,
)
import services as _services

_services.set_progress_emitter(_push)


# ── Dev entry ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("Starting Myth Forge MTG Deck Builder...", flush=True)
    print(flush=True)

    # Boot the LLM backend + ComfyUI in a background daemon thread.  _start_comfyui()
    # launches ComfyUI and then polls for up to ~2 min for it to come up; running
    # it inline blocked uvicorn from binding port 8000 whenever ComfyUI wasn't
    # already running, so the whole app appeared to "fail to start".  The app
    # already tolerates these services being briefly offline (every build runs a
    # health check and falls back), so they can warm up in parallel.
    def _boot_services():
        try:
            _start_llm_backend()
            _start_comfyui()
        except Exception as _e:
            print(f"  [!] Background service startup error: {_e}", flush=True)

    from themer import LLM_BACKEND as _boot_backend
    _boot_label = "llama-swap" if _boot_backend == "llamacpp" else "Ollama"
    print(f"Starting {_boot_label} + ComfyUI in the background (server will not wait on them)...", flush=True)
    threading.Thread(target=_boot_services, name="service-boot", daemon=True).start()

    print(flush=True)
    print("Server endpoints:", flush=True)
    print("  API:      http://localhost:8000/api/", flush=True)
    print("  Frontend: http://localhost:8000/", flush=True)
    print(flush=True)
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
