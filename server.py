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
import json
import os
import re
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import AsyncGenerator, Optional, List

import requests
from fastapi import FastAPI, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator

# ── Local modules ─────────────────────────────────────────────────────────────
from scryfall_client    import ScryfallClient
from commander_analysis import build_commander_profile
from deck_builder       import DeckBuilder, compute_stats
from playstyle          import (
    PLAYSTYLES, PLAYSTYLE_ORDER, resolve_themes, get_slot_adjustments,
)
from themer             import Themer, ThemedCard
from image_gen          import ImageGen
from card_renderer      import render_card, render_deck_thumbnails
from set_symbol         import generate_set_symbol
from exporter           import build_zip, build_pdf
from bracket            import BRACKET_LABELS
from face_ref           import get_face_paths

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="Commander Deck Builder", version="1.0")

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
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

STATIC_DIR  = Path(__file__).parent / "frontend" / "dist"
RENDER_DIR  = Path("renders")
RENDER_DIR.mkdir(exist_ok=True)

# In-memory job store (replace with Redis/SQLite for persistence)
_jobs: dict[str, dict] = {}
_progress: dict[str, list[str]] = {}   # job_id → list of SSE event strings
_JOB_TTL_SECONDS = 86400  # 24 hours — auto-expire old jobs to prevent memory accumulation

# Rate limiting for expensive endpoints (prevent resource exhaustion from floods)
_request_timestamps: dict[str, list[float]] = {}  # IP → list of request timestamps
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_BUILD_REQUESTS = 5  # max 5 builds per minute per IP

# Global art-generation lock — ComfyUI is a single-GPU resource.
# Only one build may run art gen at a time; concurrent builds queue up here.
_art_lock = threading.Lock()

# Per-source-deck lock to serialize regen-cards writes to the same deck dir.
# Without this, two concurrent regen calls on the same deck race their PNG
# writes and SSE card_ready events.
_deck_regen_locks: dict[str, threading.Lock] = {}
_deck_regen_locks_meta_lock = threading.Lock()

def _get_deck_regen_lock(source_job_id: str) -> threading.Lock:
    """Return (or create) the threading.Lock for a given source deck."""
    with _deck_regen_locks_meta_lock:
        lock = _deck_regen_locks.get(source_job_id)
        if lock is None:
            lock = threading.Lock()
            _deck_regen_locks[source_job_id] = lock
        return lock

# Shared clients (created once)
_scryfall = ScryfallClient()


# ── Job cleanup (prevent memory accumulation) ──────────────────────────────────

def _check_rate_limit(client_id: str, max_requests: int = _RATE_LIMIT_BUILD_REQUESTS) -> bool:
    """
    Check if client has exceeded rate limit (token bucket).
    Returns True if request is allowed, False if rate limited.
    """
    now = time.time()

    # Clean old timestamps outside window
    if client_id in _request_timestamps:
        _request_timestamps[client_id] = [
            ts for ts in _request_timestamps[client_id]
            if (now - ts) < _RATE_LIMIT_WINDOW
        ]

    # Check limit
    count = len(_request_timestamps.get(client_id, []))
    if count >= max_requests:
        return False  # Rate limited

    # Add new timestamp
    _request_timestamps.setdefault(client_id, []).append(now)
    return True


def _cleanup_expired_jobs():
    """Remove jobs older than _JOB_TTL_SECONDS to prevent memory leaks."""
    now = time.time()
    expired = [
        job_id for job_id, job in _jobs.items()
        if (now - job.get("created_at", now)) > _JOB_TTL_SECONDS
    ]
    for job_id in expired:
        _jobs.pop(job_id, None)
        _progress.pop(job_id, None)
    if expired:
        print(f"  [cleanup] Expired {len(expired)} old job(s) (>{_JOB_TTL_SECONDS//3600}h)")


@app.on_event("startup")
async def startup_event():
    """Run startup checks and start background cleanup when the app starts."""
    import sys
    print("\n" + "="*70, flush=True)
    print("COMMANDER DECK BUILDER - STARTUP CHECKS", flush=True)
    print("="*70, flush=True)
    _ensure_ollama_models_ready()
    print("="*70 + "\n", flush=True)
    sys.stdout.flush()

    # Start periodic cleanup of old jobs in the background
    async def cleanup_loop():
        """Run job cleanup every hour."""
        while True:
            await asyncio.sleep(3600)  # 1 hour
            _cleanup_expired_jobs()

    asyncio.create_task(cleanup_loop())


# ── Ollama model checks (startup) ──────────────────────────────────────────────

def _check_ollama_model(model_name: str, base_url: str = "http://127.0.0.1:11434") -> bool:
    """Check if an Ollama model is installed."""
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        if response.status_code != 200:
            return False
        models = response.json().get("models", [])
        return any(m["name"].startswith(model_name) for m in models)
    except Exception:
        return False


def _pull_ollama_model(model_name: str, base_url: str = "http://127.0.0.1:11434") -> bool:
    """Pull (download) an Ollama model."""
    try:
        print(f"  [startup] Pulling Ollama model: {model_name}...")
        response = requests.post(
            f"{base_url}/api/pull",
            json={"name": model_name},
            timeout=600,  # 10 minute timeout for large models
        )
        if response.status_code == 200:
            print(f"  [startup] [OK] Model pulled: {model_name}")
            return True
        else:
            print(f"  [startup] [FAIL] Failed to pull {model_name} (HTTP {response.status_code})")
            return False
    except requests.Timeout:
        print(f"  [startup] [FAIL] Timeout pulling {model_name} - increase timeout or check disk space")
        return False
    except Exception as e:
        print(f"  [startup] [FAIL] Error pulling {model_name}: {e}")
        return False


def _ensure_ollama_models_ready():
    """Check that Ollama is reachable; does NOT pull missing models (would block startup)."""
    import sys
    from themer import OLLAMA_MODEL, OLLAMA_BASE

    print("\n[startup] Checking Ollama connectivity...", flush=True)

    # Check if Ollama is reachable
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        if r.status_code == 200:
            models = r.json().get("models", [])
            print(f"  [startup] [OK] Ollama reachable - {len(models)} model(s) loaded", flush=True)
            # Check for default model
            if _check_ollama_model(OLLAMA_MODEL, OLLAMA_BASE):
                print(f"  [startup] [OK] Default model available: {OLLAMA_MODEL}", flush=True)
            else:
                print(f"  [startup] [!] Default model missing: {OLLAMA_MODEL}", flush=True)
                print(f"  [startup]     Pull before first use: ollama pull {OLLAMA_MODEL}", flush=True)
        else:
            print(f"  [startup] [FAIL] Ollama HTTP error {r.status_code}", flush=True)
    except requests.Timeout:
        print(f"  [startup] [FAIL] Ollama not reachable (timeout)", flush=True)
        print(f"  [startup]        Start Ollama before running the deck builder", flush=True)
    except Exception as e:
        print(f"  [startup] [FAIL] Ollama error: {e}", flush=True)
        print(f"  [startup]        Start Ollama before running the deck builder", flush=True)


# ── Request / Response models ─────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str

class BuildRequest(BaseModel):
    commander_name:    str = Field(..., max_length=120)
    playstyle:         str = "auto"
    # Caps prevent long appearance dumps from polluting the LLM batch prompt and
    # blowing FLUX's first-N-token attention window (causes "standing portrait"
    # output with no card action).
    art_theme:         str = Field("", max_length=400)
    commander_prompt:  str = Field("", max_length=500)
    emblem_prompt:     str = Field("", max_length=300)
    art_style:         str = "mtg_fantasy"  # LoRA preset key
    generate_art:      bool = False
    model_speed:       str  = "quality"  # "quality" (flux-dev) or "fast" (flux-schnell) or "sd35" (SD 3.5 Large)
    bracket:           int  = 3
    face_key:          Optional[str] = None   # commander face photos
    face_gender:       str = "either"         # "male", "female", or "either"
    crew_key:          Optional[str] = None   # crew face photos for creature cards
    crew_gender:       str = "either"         # gender hint for crew faces
    user_name:         Optional[str] = None   # replaces the commander's generated first name
    llm_model:         Optional[str] = None   # Ollama model key — None = use themer default
    border_theme:      str           = ""     # free-text description of card-border decoration


class RebuildRequest(BaseModel):
    """Minimal params needed to re-run art gen for an already-themed deck."""
    art_style:   str = "mtg_fantasy"
    model_speed: str = "quality"
    face_key:    Optional[str] = None
    face_gender: str = "either"
    crew_key:    Optional[str] = None
    crew_gender: str = "either"


class CardRegenEntry(BaseModel):
    render_key:    str            # safe-name used in the filename / URL
    original_name: str            # canonical MTG card name for lookup fallback
    custom_prompt: Optional[str] = None   # None → use saved art_prompt


class RegenCardsRequest(BaseModel):
    """Per-card regeneration — re-run art gen for a specific subset of cards."""
    cards:       List[CardRegenEntry]
    art_style:   str = "mtg_fantasy"
    model_speed: str = "quality"
    face_key:    Optional[str] = None   # commander face override
    face_gender: str = "either"
    crew_key:    Optional[str] = None   # crew faces override for creature cards
    crew_gender: str = "either"


class RethemeRequest(BaseModel):
    """Re-run Ollama theming for an already-built deck, keeping all existing card art."""
    art_theme:        Optional[str] = None   # None → use saved theme from deck.json
    commander_prompt: Optional[str] = None   # None → use saved commander_prompt
    user_name:        Optional[str] = None   # None → use saved user_name
    llm_model:        Optional[str] = None   # None → use saved llm_model


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _push(job_id: str, event: str, data: str):
    msg = f"event: {event}\ndata: {data}\n\n"
    _progress.setdefault(job_id, []).append(msg)

async def _sse_stream(job_id: str, request: Optional[Request] = None) -> AsyncGenerator[str, None]:
    sent = 0
    while True:
        # Stop if the client closed its EventSource (browser tab closed, etc.)
        if request is not None and await request.is_disconnected():
            break
        msgs = _progress.get(job_id, [])
        while sent < len(msgs):
            yield msgs[sent]
            sent += 1
        job = _jobs.get(job_id, {})
        if job.get("status") in ("done", "error"):
            # Drain any final messages pushed between the message pump and the
            # status check — the worker thread may push "done"/"error" after we
            # already snapshotted msgs above.
            msgs = _progress.get(job_id, [])
            while sent < len(msgs):
                yield msgs[sent]
                sent += 1
            break
        await asyncio.sleep(0.3)


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

_VRAM_FLUX_REQUIRED_GB  = 16.0   # minimum free VRAM before loading FLUX+LoRAs
_VRAM_OLLAMA_CLEAR_GB   = 18.0   # target free VRAM after Ollama eviction
                                  # (24 GB card − 6 GB OS/driver overhead = 18 GB "clear")
_EVICT_POLL_INTERVAL    = 3.0    # seconds between VRAM polls (increased from 2.0 for efficiency)
_EVICT_MAX_WAIT         = 120    # seconds — large models (27B, 23 GB) need up to 60 s


def _comfyui_vram_free_gb() -> Optional[float]:
    """Return free VRAM (GB) reported by ComfyUI /system_stats, or None on error."""
    try:
        r = requests.get("http://127.0.0.1:8188/system_stats", timeout=4)
        if r.status_code == 200:
            devices = r.json().get("devices", [])
            for dev in devices:
                if "vram_free" in dev:
                    return dev["vram_free"] / (1024 ** 3)
    except Exception:
        pass
    return None


def _wait_for_vram(threshold_gb: float, max_wait: float = _EVICT_MAX_WAIT,
                   job_id: str = "", label: str = "") -> bool:
    """
    Poll ComfyUI /system_stats until free VRAM >= threshold_gb.
    Returns True if threshold reached, False if timed out.
    This is the single authoritative gate before loading any large model.
    """
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        free_gb = _comfyui_vram_free_gb()
        if free_gb is None:
            return True   # ComfyUI offline — no VRAM contest, proceed
        if free_gb >= threshold_gb:
            if job_id:
                print(f"  [vram] [OK] {label or 'VRAM'} clear: {free_gb:.1f} GB free "
                      f"(need {threshold_gb:.0f}+)")
            return True
        if job_id:
            print(f"  [vram] Waiting… {free_gb:.1f} GB free "
                  f"(need {threshold_gb:.0f}+ for {label or 'next step'})")
        time.sleep(_EVICT_POLL_INTERVAL)
    free_gb = _comfyui_vram_free_gb()
    if job_id:
        _vram_str = f"{free_gb:.1f}" if free_gb is not None else "?"
        print(f"  [vram] [!] VRAM wait timeout - "
              f"{_vram_str} GB free, need {threshold_gb:.0f}+")
    return False


def _wait_for_comfyui_unload(job_id: str = "") -> bool:
    """
    Tell ComfyUI to unload all models, then wait for VRAM to actually clear.
    Returns True if VRAM freed, False if timed out or ComfyUI offline.
    """
    try:
        requests.post(
            "http://127.0.0.1:8188/free",
            json={"unload_models": True, "free_memory": True},
            timeout=8,
        )
    except Exception:
        return False  # ComfyUI offline — nothing to free

    # Use the Ollama-clear threshold here: after unloading FLUX we want plenty
    # of headroom for the LLM that's about to load.
    return _wait_for_vram(_VRAM_OLLAMA_CLEAR_GB, job_id=job_id, label="ComfyUI unload")


def _ollama_loaded_models() -> list[str]:
    """Return list of currently-loaded Ollama model names (via /api/ps)."""
    try:
        r = requests.get("http://127.0.0.1:11434/api/ps", timeout=4)
        if r.status_code == 200:
            return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


def _wait_for_ollama_evict(model: str, job_id: str = "") -> bool:
    """
    Evict `model` from Ollama VRAM via keep_alive=0, then perform a TWO-STAGE
    confirmation:
      1. Poll /api/ps until the model disappears from Ollama's process list.
      2. Poll ComfyUI /system_stats until free VRAM >= _VRAM_FLUX_REQUIRED_GB.

    Stage 2 is the critical one that was missing before.  Ollama can report a
    model as "unloaded" while CUDA still holds the physical pages cached.
    Loading FLUX on top of those cached pages causes the OOM Windows crash.

    Fast-path: if no models are loaded AND VRAM is already sufficient, skip
    all eviction work.  This avoids 20 s of dead POST timeouts on rebuild/regen
    jobs where Ollama was never used in this session.
    """
    # Fast-path: check VRAM first (cheap, single HTTP call).  If we already
    # have enough headroom there's nothing to evict — don't even hit Ollama.
    free_now = _comfyui_vram_free_gb()
    if free_now is not None and free_now >= _VRAM_FLUX_REQUIRED_GB:
        if job_id:
            print(f"  [vram] Ollama evict skipped — VRAM already clear "
                  f"({free_now:.1f} GB free, need {_VRAM_FLUX_REQUIRED_GB:.0f}+)")
        return True

    # VRAM is tight — check if anything is actually loaded before sending
    # keep_alive=0.  If Ollama is idle/offline, skip the POST requests (each
    # has a 10 s timeout that adds dead wait before FLUX can start).
    loaded_now = _ollama_loaded_models()
    model_base = model.split(":")[0]
    model_is_loaded = any(model_base in m for m in loaded_now)

    if not model_is_loaded and not loaded_now:
        # Nothing loaded — VRAM pressure must be from something else (e.g. a
        # previous ComfyUI run still resident).  Skip Ollama POST, go straight
        # to VRAM poll so we still gate on physical memory clearing.
        if job_id:
            print(f"  [vram] Ollama idle — skipping keep_alive=0, waiting for VRAM…")
        return _wait_for_vram(_VRAM_FLUX_REQUIRED_GB, job_id=job_id,
                              label="pre-FLUX VRAM gate")

    # Send eviction request via both endpoints — models loaded via chat API
    # sometimes don't respond to the /api/generate keep_alive signal alone.
    for endpoint in ("/api/generate", "/api/chat"):
        try:
            payload = ({"model": model, "keep_alive": 0} if endpoint == "/api/generate"
                       else {"model": model, "keep_alive": 0,
                             "messages": [{"role": "user", "content": ""}]})
            requests.post(f"http://127.0.0.1:11434{endpoint}", json=payload, timeout=10)
        except Exception:
            pass

    # Stage 1 — wait for Ollama to drop the model from /api/ps
    stage1_ok  = False
    deadline   = time.monotonic() + _EVICT_MAX_WAIT
    while time.monotonic() < deadline:
        time.sleep(_EVICT_POLL_INTERVAL)
        loaded       = _ollama_loaded_models()
        still_loaded = [m for m in loaded if model_base in m]
        if not still_loaded:
            if job_id:
                print(f"  [vram] Ollama: '{model}' removed from process list")
            stage1_ok = True
            break
        if job_id:
            print(f"  [vram] Waiting for Ollama to drop '{model}'… still loaded: {still_loaded}")

    if not stage1_ok and job_id:
        print(f"  [vram] [!] Ollama did not drop '{model}' within {_EVICT_MAX_WAIT}s - "
              f"proceeding to VRAM check anyway")

    # Stage 2 — wait for physical VRAM to clear (the part that was missing)
    # Even if Stage 1 timed out, CUDA may still eventually release pages.
    # Give up to _EVICT_MAX_WAIT more seconds for VRAM to actually free.
    remaining = max(10.0, _EVICT_MAX_WAIT - (_EVICT_MAX_WAIT if not stage1_ok else 0))
    stage2_ok = _wait_for_vram(
        _VRAM_FLUX_REQUIRED_GB,
        max_wait=remaining,
        job_id=job_id,
        label=f"post-Ollama evict ({model})",
    )

    if stage2_ok and job_id:
        print(f"  [vram] [OK] Ollama evict + VRAM clear confirmed for '{model}'")
    elif job_id:
        free = _comfyui_vram_free_gb()
        _free_str = f"{free:.1f}" if free is not None else "?"
        print(f"  [vram] [!] VRAM not fully clear after Ollama evict "
              f"({_free_str} GB free, need {_VRAM_FLUX_REQUIRED_GB}+) — "
              f"art gen may fail")

    return stage1_ok and stage2_ok


def _free_all_vram(job_id: str = "") -> None:
    """
    Fire-and-forget VRAM cleanup triggered on job cancel.

    Sends unload/eviction requests to ComfyUI and Ollama and returns
    immediately — deliberately does NOT poll/wait for VRAM to confirm.

    Why fire-and-forget instead of blocking?
      • _wait_for_comfyui_unload() polls for _VRAM_OLLAMA_CLEAR_GB (18 GB) free,
        but CUDA's caching allocator keeps freed PyTorch pages resident until
        torch.cuda.empty_cache() completes, which may never drive vram_free above
        the threshold within _EVICT_MAX_WAIT (120 s) on --highvram ComfyUI.
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
    # Send Ollama eviction requests (fire-and-forget — no keep_alive poll)
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
    """
    if not oracle_text or not original_name or not themed_name:
        return oracle_text
    # Full-name replacement (literal — names can contain punctuation that
    # would need escaping in a regex)
    result = oracle_text.replace(original_name, themed_name)
    # Short-form self-references — Scryfall oracle text uses an abbreviated form:
    #   • Comma-based names: just the pre-comma part ("Uro, Titan…" → "Uro attacks")
    #   • No-comma multi-word names: just the first word ("Kaalia of the Vast" → "Kaalia attacks")
    first_orig   = original_name.split(",")[0].strip()
    first_themed = themed_name.split(",")[0].strip()
    if first_orig and len(first_orig) > 2:
        if first_orig != original_name:
            # Comma-based name — pre-comma part is a distinct short form
            result = re.sub(rf"\b{re.escape(first_orig)}\b", first_themed, result)
        elif " " in first_orig:
            # No-comma multi-word name — Scryfall uses just the first word as shorthand
            first_word = first_orig.split()[0]
            if len(first_word) > 2:
                result = re.sub(rf"\b{re.escape(first_word)}\b", first_themed, result)
    return result


# ── User-name substitution helper ────────────────────────────────────────────

def _apply_user_name(themed_name: str, user_name: str) -> str:
    """
    Replace the personal-name portion of a legendary themed name with the
    player's chosen name.

    Examples:
      "Vex Thornwood, Blade of the Void" + "Dorian"  → "Dorian, Blade of the Void"
      "Vex Thornwood, Blade of the Void" + "Dorian Grey" → "Dorian Grey, Blade of the Void"
      "Ember Sanctum"  (no comma, non-legendary) + "Dorian" → "Ember Sanctum" (unchanged)
    """
    user_name = (user_name or "").strip()
    if not user_name:
        return themed_name
    if "," in themed_name:
        _, rest = themed_name.split(",", 1)
        return f"{user_name},{rest}"
    # No comma → keep the generated name (non-legendary flat names don't need replacing)
    return themed_name


# ── Background deck build ─────────────────────────────────────────────────────

def _run_build(job_id: str, req: BuildRequest):
    try:
        _jobs[job_id]["status"] = "building"

        # ── Commander lookup ──────────────────────────────────────────────────
        _push(job_id, "progress", json.dumps({"step": "commander", "msg": f"Looking up {req.commander_name}..."}))
        card = _scryfall.get_card_by_name(req.commander_name, fuzzy=True)
        if not card:
            raise ValueError(f"Commander not found: {req.commander_name}")
        _push(job_id, "progress", json.dumps({"step": "commander", "msg": f"Found: {card['name']}"}))

        # ── Profile + playstyle ───────────────────────────────────────────────
        profile        = build_commander_profile(card)
        active_themes  = resolve_themes(req.playstyle, profile.themes)
        slot_overrides = get_slot_adjustments(req.playstyle)
        ps_label       = PLAYSTYLES.get(req.playstyle, PLAYSTYLES["auto"])["label"]

        # ── Deck build ────────────────────────────────────────────────────────
        _push(job_id, "progress", json.dumps({"step": "deck", "msg": "Building 99-card deck..."}))
        builder = DeckBuilder(_scryfall)
        deck = builder.build(
            profile,
            theme_override  = active_themes,
            slot_overrides  = slot_overrides,
            playstyle_label = ps_label,
            bracket         = req.bracket,
        )
        stats = compute_stats(card, deck)
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

        # Free ComfyUI FLUX from VRAM before Ollama runs.
        # With --highvram, FLUX stays resident between builds (~12 GB).
        # Polling /system_stats ensures VRAM is actually free before Ollama loads.
        _push(job_id, "progress", json.dumps({"step": "theme", "msg": "Freeing GPU for Ollama…"}))
        _wait_for_comfyui_unload(job_id)

        _llm = req.llm_model or None   # None → Themer uses default qwen3:14b
        _push(job_id, "progress", json.dumps({
            "step": "theme",
            "msg":  f"Theming cards with Ollama ({_llm or 'default'})..."
        }))

        themed_cmd: Optional[ThemedCard] = None
        themed_deck: Optional[list[ThemedCard]] = None
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
            )
            _push(job_id, "progress", json.dumps({"step": "theme", "msg": "Theming complete",
                                                   "pct": 100}))
        except Exception as e:
            print(f"  [theme] OLLAMA THEMING ERROR: {e}")
            traceback.print_exc()
            _push(job_id, "progress", json.dumps({
                "step": "theme",
                "msg": f"[!] Ollama theming failed — falling back to plain card names. Error: {e}",
                "warning": True,
            }))

        if themed_cmd is None:
            def _plain(c): return ThemedCard(c["name"], c["name"], "", "", c)
            themed_cmd  = _plain(card)
            themed_deck = [_plain(c) for c in deck]

        # ── Apply user's custom name to the commander ─────────────────────────
        if req.user_name:
            themed_cmd.themed_name = _apply_user_name(themed_cmd.themed_name, req.user_name)
            _push(job_id, "progress", json.dumps({
                "step": "theme",
                "msg":  f"Commander renamed: {themed_cmd.themed_name}",
            }))

        # ── Set symbol ────────────────────────────────────────────────────────
        _push(job_id, "progress", json.dumps({"step": "symbol", "msg": "Generating set symbol..."}))
        sym      = generate_set_symbol(art_theme, emblem_prompt=req.emblem_prompt or "")
        sym_path = RENDER_DIR / job_id / "set_symbol.png"
        sym_path.parent.mkdir(parents=True, exist_ok=True)
        sym.save(sym_path)

        # ── Build result dict helper ──────────────────────────────────────────
        def _tc_to_dict(tc: ThemedCard, deck_index: int = 0, has_render: bool = False) -> dict:
            c = tc.card
            safe = "".join(ch if ch.isalnum() else "_" for ch in tc.original_name)[:48]
            # Append deck index to render_key to disambiguate duplicate cards
            render_key = f"{safe}_{deck_index:03d}"
            # Replace any self-references in oracle text with the themed name
            oracle = _replace_card_self_ref(
                c.get("oracle_text", ""), tc.original_name, tc.themed_name
            )
            return {
                "original_name": tc.original_name,
                "themed_name":   tc.themed_name,
                "art_prompt":    tc.art_prompt,
                "flavor_text":   tc.flavor_text,
                "mana_cost":     c.get("mana_cost", ""),
                "type_line":     c.get("type_line", ""),
                "oracle_text":   oracle,
                "cmc":           c.get("cmc", 0),
                "colors":        c.get("color_identity", []),
                "power":         c.get("power"),
                "toughness":     c.get("toughness"),
                "scryfall_img":  (c.get("image_uris") or {}).get("normal", ""),
                "has_render":    has_render,
                "render_key":    render_key,
            }

        # ── Early checkpoint: write deck.json NOW (before art gen + render) ──
        # Art gen is the longest step (30+ min). If the server crashes or
        # reloads during that step, the themed deck data is preserved here.
        deck_json_path = RENDER_DIR / job_id / "deck.json"
        deck_json_path.parent.mkdir(parents=True, exist_ok=True)
        # Compute deck_slug here so it's available for retheme later
        _deck_slug_base = ("".join(c if c.isalnum() else "_" for c in card["name"])[:28]
                           + "_" + job_id[:8])
        checkpoint = {
            "status":           "rendering",   # updated to "done" at the end
            "commander":        _tc_to_dict(themed_cmd, deck_index=0),
            "deck":             [_tc_to_dict(tc, deck_index=i) for i, tc in enumerate(themed_deck, 1)],
            "stats":            stats,
            "theme":            art_theme,
            "commander_prompt": req.commander_prompt,
            "emblem_prompt":    req.emblem_prompt,
            "playstyle":        ps_label,
            "bracket":          req.bracket,
            "bracket_label":    BRACKET_LABELS.get(req.bracket, str(req.bracket)),
            "art_style":        req.art_style,
            "model_speed":      req.model_speed,
            "generate_art":     req.generate_art,
            "deck_slug":        _deck_slug_base,
            "face_key":         req.face_key or "",
            "face_gender":      req.face_gender,
            "crew_key":         req.crew_key or "",
            "crew_gender":      req.crew_gender,
            "user_name":        req.user_name or "",
            "llm_model":        req.llm_model or "",
            "border_theme":     req.border_theme or "",
            "built_at":         time.time(),
        }
        deck_json_path.write_text(json.dumps(checkpoint), encoding="utf-8")

        # render_out is defined early so the inline-render callback can use it
        render_out = RENDER_DIR / job_id / "cards"
        render_out.mkdir(parents=True, exist_ok=True)
        cancel_event = _jobs[job_id].get("cancel_event") or threading.Event()

        # ── Art generation (optional) ─────────────────────────────────────────
        art_paths: dict[str, Optional[Path]] = {}
        if req.generate_art:
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
                _push(job_id, "progress", json.dumps({"step": "art", "msg": f"Evicting Ollama ({_evict_model}) from VRAM…"}))
                _wait_for_ollama_evict(_evict_model, job_id)

                _push(job_id, "progress", json.dumps({"step": "art", "msg": "Waiting for GPU…"}))
                with _art_lock:   # serialize: only one build drives ComfyUI at a time
                    try:
                        gen = ImageGen(model_speed=req.model_speed, art_style=req.art_style)
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

                        def _art_cb(card_num, total, card_name, has_face, elapsed, success):
                            pct = round(card_num / total * 100, 1) if total else 0
                            done_so_far = card_num
                            # Rolling ETA: avg seconds per card × remaining cards
                            wall_elapsed = time.time() - _art_start_time
                            avg_secs = wall_elapsed / done_so_far if done_so_far else elapsed
                            remaining = total - done_so_far
                            eta_secs  = round(avg_secs * remaining)
                            _push(job_id, "progress", json.dumps({
                                "step":      "art",
                                "msg":       f"[{card_num}/{total}] {card_name}",
                                "card_num":  card_num,
                                "total":     total,
                                "card_name": card_name,
                                "has_face":  has_face,
                                "pct":       pct,
                                "elapsed":   round(wall_elapsed),
                                "eta":       eta_secs,
                                "last_ok":   success,
                            }))

                        # Pre-compute render_keys for indexed filenames (used in card_done_cb)
                        _render_keys_inline = {}
                        _render_keys_inline[themed_cmd.original_name] = f"{_safe_name(themed_cmd.original_name)}_000"
                        for i, tc in enumerate(themed_deck, 1):
                            _render_keys_inline[tc.original_name] = f"{_safe_name(tc.original_name)}_{i:03d}"

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
                                progress_callback=_art_cb,
                                theme_str=art_theme,
                                card_done_callback=_card_done_cb,
                                cancel_event=cancel_event,
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
        # Reuse the render_keys computed earlier (already set in _render_keys_inline)
        saved_imgs = render_deck_thumbnails(
            themed_cmd, themed_deck, art_theme, art_paths, render_out,
            oracle_overrides=_oracle_ov,
            flavor_overrides=_flavor_ov,
            border_theme=req.border_theme or "",
            render_keys=_render_keys_inline,
        )
        _push(job_id, "progress", json.dumps({"step": "render", "msg": f"Rendered {len(saved_imgs)} card frames"}))

        # ── Finalize result ───────────────────────────────────────────────────
        # Re-serialize with has_render flags set correctly, then overwrite checkpoint
        result = dict(checkpoint)
        result["status"]    = "done"
        result["commander"] = _tc_to_dict(themed_cmd, deck_index=0, has_render=themed_cmd.original_name in saved_imgs)
        result["deck"]      = [_tc_to_dict(tc, deck_index=i, has_render=tc.original_name in saved_imgs) for i, tc in enumerate(themed_deck, 1)]
        _jobs[job_id].update(result)

        # Overwrite checkpoint with final done state
        deck_json_path.write_text(json.dumps(result), encoding="utf-8")

        _push(job_id, "done", json.dumps({"job_id": job_id}))

    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"]  = str(e)
        _push(job_id, "error", json.dumps({"msg": str(e)}))
        traceback.print_exc()   # full stack trace to server stdout/log
    finally:
        # The cancel_event is only useful during the build itself.  Drop it
        # now so it can't leak into JSON responses (it's a threading.Event,
        # which FastAPI's encoder cannot serialize — this was the cause of
        # the 500 errors on /api/deck/{job_id} after a successful build).
        _jobs.get(job_id, {}).pop("cancel_event", None)
        # Cap the per-job progress buffer (keep most recent events for late SSE
        # clients to drain). Without this, ETA-ticker spam accumulates forever.
        msgs = _progress.get(job_id)
        if msgs and len(msgs) > 80:
            _progress[job_id] = msgs[-80:]
        # Cap the in-memory job store. Once deck.json is on disk, /api/deck/{id}
        # endpoints fall back to disk transparently, so we can drop heavy payloads.
        _trim_in_memory_jobs()


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
        source_path = RENDER_DIR / source_job_id / "deck.json"
        if not source_path.exists():
            disk = _load_deck_from_disk(source_job_id)
            if not disk:
                raise ValueError(f"Source deck not found: {source_job_id}")
            source_data = disk
        else:
            source_data = json.loads(source_path.read_text(encoding="utf-8"))

        _push(job_id, "progress", json.dumps({"step": "deck", "msg": "Loading saved deck and prompts…"}))

        # Reconstruct ThemedCard objects from stored card dicts
        def _dict_to_tc(d: dict) -> ThemedCard:
            return ThemedCard(
                original_name = d["original_name"],
                themed_name   = d["themed_name"],
                art_prompt    = d.get("art_prompt", ""),
                flavor_text   = d.get("flavor_text", ""),
                card          = {
                    "name":           d["original_name"],
                    "mana_cost":      d.get("mana_cost", ""),
                    "type_line":      d.get("type_line", ""),
                    "oracle_text":    d.get("oracle_text", ""),
                    "cmc":            d.get("cmc", 0),
                    "color_identity": d.get("colors", []),
                    "power":          d.get("power"),
                    "toughness":      d.get("toughness"),
                    "image_uris":     {"normal": d["scryfall_img"]} if d.get("scryfall_img") else {},
                },
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
        render_out = RENDER_DIR / job_id / "cards"
        render_out.mkdir(parents=True, exist_ok=True)
        sym_path = RENDER_DIR / job_id / "set_symbol.png"

        old_sym = RENDER_DIR / source_job_id / "set_symbol.png"
        if old_sym.exists():
            _shutil.copy2(old_sym, sym_path)
            from PIL import Image as _PIL
            sym = _PIL.open(sym_path)
        else:
            _push(job_id, "progress", json.dumps({"step": "symbol", "msg": "Regenerating set symbol…"}))
            sym = generate_set_symbol(art_theme, emblem_prompt=source_data.get("emblem_prompt", ""))
            sym.save(sym_path)

        # ── Helper (identical to _run_build) ─────────────────────────────────
        def _tc_to_dict(tc: ThemedCard, deck_index: int = 0, has_render: bool = False) -> dict:
            c = tc.card
            safe = "".join(ch if ch.isalnum() else "_" for ch in tc.original_name)[:48]
            render_key = f"{safe}_{deck_index:03d}"
            oracle = _replace_card_self_ref(
                c.get("oracle_text", ""), tc.original_name, tc.themed_name
            )
            return {
                "original_name": tc.original_name,
                "themed_name":   tc.themed_name,
                "art_prompt":    tc.art_prompt,
                "flavor_text":   tc.flavor_text,
                "mana_cost":     c.get("mana_cost", ""),
                "type_line":     c.get("type_line", ""),
                "oracle_text":   oracle,
                "cmc":           c.get("cmc", 0),
                "colors":        c.get("color_identity", []),
                "power":         c.get("power"),
                "toughness":     c.get("toughness"),
                "scryfall_img":  (c.get("image_uris") or {}).get("normal", ""),
                "has_render":    has_render,
                "render_key":    render_key,
            }

        cancel_event = _jobs[job_id].get("cancel_event") or threading.Event()

        # Compute a new deck_slug for the rebuild's art cache directory
        _rebuild_deck_slug = ("".join(c if c.isalnum() else "_" for c in themed_cmd.original_name)[:28]
                              + "_" + job_id[:8])

        # ── Write checkpoint ─────────────────────────────────────────────────
        deck_json_path = RENDER_DIR / job_id / "deck.json"
        checkpoint = {
            "status":           "rendering",
            "commander":        _tc_to_dict(themed_cmd, deck_index=0),
            "deck":             [_tc_to_dict(tc, deck_index=i) for i, tc in enumerate(themed_deck, 1)],
            "stats":            stats,
            "theme":            art_theme,
            "commander_prompt": req.commander_prompt or source_data.get("commander_prompt", ""),
            "emblem_prompt":    source_data.get("emblem_prompt", ""),
            "playstyle":        source_data.get("playstyle", ""),
            "bracket":          source_data.get("bracket", 3),
            "bracket_label":    source_data.get("bracket_label", ""),
            "art_style":        req.art_style,
            "model_speed":      req.model_speed,
            "generate_art":     True,
            "deck_slug":        _rebuild_deck_slug,
            "face_key":         req.face_key or source_data.get("face_key", ""),
            "face_gender":      req.face_gender or source_data.get("face_gender", "either"),
            "crew_key":         req.crew_key or source_data.get("crew_key", ""),
            "crew_gender":      req.crew_gender or source_data.get("crew_gender", "either"),
            "border_theme":     source_data.get("border_theme", ""),
            "rebuilt_from":     source_job_id,
            "built_at":         time.time(),
        }
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
            art_dir = Path("generated_art") / slug
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
                parent_path = RENDER_DIR / parent_id / "deck.json"
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
            # Evict Ollama from VRAM and confirm before loading FLUX.
            from themer import OLLAMA_MODEL as _DEFAULT_OLLAMA
            _evict_rt = source_data.get("llm_model") or _DEFAULT_OLLAMA
            _push(job_id, "progress", json.dumps({"step": "art", "msg": f"Evicting Ollama ({_evict_rt}) from VRAM…"}))
            _wait_for_ollama_evict(_evict_rt, job_id)

            _push(job_id, "progress", json.dumps({"step": "art", "msg": "Waiting for GPU…"}))
            with _art_lock:
                try:
                    gen = ImageGen(model_speed=req.model_speed, art_style=req.art_style)
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

                    def _art_cb(card_num, total, card_name, has_face, elapsed, success):
                        pct = round(card_num / total * 100, 1) if total else 0
                        wall_elapsed = time.time() - _art_start_time
                        avg_secs = wall_elapsed / card_num if card_num else elapsed
                        eta_secs = round(avg_secs * (total - card_num))
                        _push(job_id, "progress", json.dumps({
                            "step":      "art",
                            "msg":       f"[{card_num}/{total}] {card_name}",
                            "card_num":  card_num,
                            "total":     total,
                            "card_name": card_name,
                            "has_face":  has_face,
                            "pct":       pct,
                            "elapsed":   round(wall_elapsed),
                            "eta":       eta_secs,
                            "last_ok":   success,
                        }))

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
                    try:
                        art_paths = gen.generate_deck(
                            themed_cmd, themed_deck, deck_slug,
                            face_paths=face_paths or None,
                            crew_paths=crew_paths or None,
                            face_gender=_face_gender,
                            crew_gender=_crew_gender,
                            progress_callback=_art_cb,
                            theme_str=art_theme,
                            card_done_callback=_card_done_cb,
                            cancel_event=cancel_event,
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
        # Build render_keys mapping for indexed filenames
        _render_keys_rb = {}
        _render_keys_rb[themed_cmd.original_name] = f"{_safe_name(themed_cmd.original_name)}_000"
        for i, tc in enumerate(themed_deck, 1):
            _render_keys_rb[tc.original_name] = f"{_safe_name(tc.original_name)}_{i:03d}"
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
        result["commander"] = _tc_to_dict(themed_cmd, deck_index=0, has_render=themed_cmd.original_name in saved_imgs)
        result["deck"]      = [_tc_to_dict(tc, deck_index=i, has_render=tc.original_name in saved_imgs) for i, tc in enumerate(themed_deck, 1)]
        _jobs[job_id].update(result)
        deck_json_path.write_text(json.dumps(result), encoding="utf-8")

        _push(job_id, "done", json.dumps({"job_id": job_id}))

    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"]  = str(e)
        _push(job_id, "error", json.dumps({"msg": str(e)}))
        traceback.print_exc()
    finally:
        _jobs.get(job_id, {}).pop("cancel_event", None)
        msgs = _progress.get(job_id)
        if msgs and len(msgs) > 80:
            _progress[job_id] = msgs[-80:]
        _trim_in_memory_jobs()


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
    from pathlib import Path as _Path

    # Per-deck serialization gate — see _get_deck_regen_lock docstring.
    _deck_lock = _get_deck_regen_lock(source_job_id)
    _deck_lock.acquire()

    try:
        _jobs[job_id]["status"] = "building"

        # ── Load source deck ──────────────────────────────────────────────────
        source_json_path = RENDER_DIR / source_job_id / "deck.json"
        if source_json_path.exists():
            source_data = json.loads(source_json_path.read_text(encoding="utf-8"))
        else:
            source_data = _load_deck_from_disk(source_job_id)
        if not source_data:
            raise ValueError(f"Source deck not found: {source_job_id}")

        # Index by render_key and by original_name for robust matching
        all_stored = [source_data["commander"]] + source_data["deck"]
        key_map:  dict[str, dict] = {}
        name_map: dict[str, dict] = {}
        for cd in all_stored:
            safe = "".join(ch if ch.isalnum() else "_" for ch in cd["original_name"])[:48]
            key_map[safe]              = cd
            name_map[cd["original_name"]] = cd

        # ── Build target list ─────────────────────────────────────────────────
        to_regen: list[tuple[ThemedCard, str, bool]] = []   # (tc, render_key, has_custom)
        for entry in req.cards:
            cd = key_map.get(entry.render_key) or name_map.get(entry.original_name)
            if not cd:
                _push(job_id, "progress", json.dumps({
                    "step": "art",
                    "msg":  f"⚠ Card not found: {entry.original_name} — skipping",
                }))
                continue

            safe   = "".join(ch if ch.isalnum() else "_" for ch in cd["original_name"])[:48]
            custom = entry.custom_prompt.strip() if entry.custom_prompt and entry.custom_prompt.strip() else ""
            prompt = custom or cd.get("art_prompt", "") or cd["original_name"]

            tc = ThemedCard(
                original_name = cd["original_name"],
                themed_name   = cd["themed_name"],
                art_prompt    = prompt,
                flavor_text   = cd.get("flavor_text", ""),
                card          = {
                    "name":           cd["original_name"],
                    "mana_cost":      cd.get("mana_cost", ""),
                    "type_line":      cd.get("type_line", ""),
                    "oracle_text":    cd.get("oracle_text", ""),
                    "cmc":            cd.get("cmc", 0),
                    "color_identity": cd.get("colors", []),
                    "power":          cd.get("power"),
                    "toughness":      cd.get("toughness"),
                    "image_uris":     {"normal": cd["scryfall_img"]} if cd.get("scryfall_img") else {},
                },
            )
            to_regen.append((tc, safe, bool(custom)))

        if not to_regen:
            raise ValueError("No matching cards found to regenerate")

        n = len(to_regen)
        _push(job_id, "progress", json.dumps({
            "step": "art",
            "msg":  f"Regenerating {n} card{'' if n == 1 else 's'}…",
        }))

        art_theme  = source_data.get("theme", "")
        sym_path   = RENDER_DIR / source_job_id / "set_symbol.png"
        sym        = _PIL.open(sym_path) if sym_path.exists() else None

        # Renders go directly into the SOURCE job's cards/ dir
        render_out = RENDER_DIR / source_job_id / "cards"
        render_out.mkdir(parents=True, exist_ok=True)

        # Which card is the commander — face conditioning applies only to it
        commander_original_name = source_data.get("commander", {}).get("original_name", "")

        # Effective face/crew settings: request overrides stored deck values
        effective_face_key    = req.face_key  or source_data.get("face_key")  or ""
        effective_face_gender = req.face_gender or source_data.get("face_gender") or "either"
        effective_crew_key    = req.crew_key  or source_data.get("crew_key")  or ""
        effective_crew_gender = req.crew_gender or source_data.get("crew_gender") or "either"

        # ── ComfyUI pre-flight ────────────────────────────────────────────────
        health = ImageGen.health_check()
        if not health["ok"]:
            raise ValueError(f"ComfyUI not available: {health['message']}")

        # Evict Ollama from VRAM and confirm before loading FLUX.
        from themer import OLLAMA_MODEL as _DEFAULT_OLLAMA
        _evict_rg = source_data.get("llm_model") or _DEFAULT_OLLAMA
        _push(job_id, "progress", json.dumps({"step": "art", "msg": f"Evicting Ollama ({_evict_rg}) from VRAM…"}))
        _wait_for_ollama_evict(_evict_rg, job_id)

        cancel_event = _jobs[job_id].get("cancel_event") or threading.Event()

        _push(job_id, "progress", json.dumps({"step": "art", "msg": "Waiting for GPU…"}))
        with _art_lock:
            gen = ImageGen(model_speed=req.model_speed, art_style=req.art_style)
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
                tc.original_name == commander_original_name for tc, _, _ in to_regen
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

            _art_start   = time.time()
            total        = len(to_regen)
            crew_regen_idx = 0   # round-robin index for crew faces

            from face_ref import is_human_card as _is_human_card

            for i, (tc, render_key, has_custom) in enumerate(to_regen, 1):
                if cancel_event.is_set():
                    break

                # Face conditioning: commander face for commander, crew for humanoid creatures
                is_commander = tc.original_name == commander_original_name
                face_for_card   = None
                gender_for_card = "either"
                if is_commander and face_comfy_name_for_cmd:
                    face_for_card   = face_comfy_name_for_cmd
                    gender_for_card = effective_face_gender
                elif not is_commander and crew_comfy_names and _is_human_card(tc.card.get("type_line", "")):
                    face_for_card   = crew_comfy_names[crew_regen_idx % len(crew_comfy_names)]
                    gender_for_card = effective_crew_gender
                    crew_regen_idx += 1

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
                    str(_Path("generated_art") / deck_slug / render_key),
                    face_comfy_name=face_for_card,
                    face_gender=gender_for_card,
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
                            border_theme=source_data.get("border_theme", ""),
                        )
                        card_img.save(out_path, "PNG")
                        _push(job_id, "card_ready", json.dumps({
                            "key":           render_key,
                            "name":          tc.themed_name,
                            "source_job_id": source_job_id,
                        }))
                    except Exception as _re:
                        print(f"  [regen] render failed for {tc.themed_name}: {_re}")

        # ── Early-exit on cancel ─────────────────────────────────────────────
        if cancel_event.is_set():
            _jobs[job_id]["status"] = "cancelled"
            _push(job_id, "done", json.dumps({"job_id": job_id, "cancelled": True}))
            return

        # ── Persist any custom prompts back to the source deck.json ──────────
        custom_updates = {
            "".join(ch if ch.isalnum() else "_" for ch in e.original_name)[:48]: e.custom_prompt.strip()
            for e in req.cards
            if e.custom_prompt and e.custom_prompt.strip()
        }
        if custom_updates:
            updated = dict(source_data)

            def _patch_prompt(cd):
                safe = "".join(ch if ch.isalnum() else "_" for ch in cd["original_name"])[:48]
                return {**cd, "art_prompt": custom_updates[safe]} if safe in custom_updates else cd

            updated["commander"] = _patch_prompt(updated["commander"])
            updated["deck"]      = [_patch_prompt(c) for c in updated["deck"]]
            source_json_path.write_text(json.dumps(updated), encoding="utf-8")

            # Keep in-memory copy consistent
            if source_job_id in _jobs and isinstance(_jobs[source_job_id].get("deck"), list):
                _jobs[source_job_id]["commander"] = updated["commander"]
                _jobs[source_job_id]["deck"]      = updated["deck"]

        _push(job_id, "done", json.dumps({"job_id": job_id, "source_job_id": source_job_id}))

    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"]  = str(e)
        _push(job_id, "error", json.dumps({"msg": str(e)}))
        traceback.print_exc()
    finally:
        # Release the per-deck regen lock before any other cleanup so a queued
        # concurrent regen on the same deck doesn't wait on this thread's
        # bookkeeping work.
        try:
            _deck_lock.release()
        except RuntimeError:
            pass   # already released or never acquired — best-effort
        _jobs.get(job_id, {}).pop("cancel_event", None)
        msgs = _progress.get(job_id)
        if msgs and len(msgs) > 80:
            _progress[job_id] = msgs[-80:]
        _trim_in_memory_jobs()


# ── Retheme: re-run Ollama theming, keep existing art ────────────────────────

def _run_retheme(job_id: str, source_job_id: str, req: RethemeRequest):
    """
    Re-run Ollama theming for an already-built deck without regenerating any art.

    Flow:
      1. Load source deck.json — recovers commander/deck card data + theme params.
      2. Re-run themer.theme_deck() with the same (or overridden) theme string.
      3. Locate existing raw FLUX art images via the stored deck_slug.
      4. Re-render every card frame with new themed names / flavor text.
      5. Write a new deck.json under job_id so the original deck is preserved.

    The new job lives in RENDER_DIR/{job_id}/.  The client navigates to it just
    like a fresh build result.
    """
    import shutil as _shutil

    try:
        _jobs[job_id]["status"] = "building"

        # ── Load source deck ──────────────────────────────────────────────────
        source_path = RENDER_DIR / source_job_id / "deck.json"
        if source_path.exists():
            source_data = json.loads(source_path.read_text(encoding="utf-8"))
        else:
            source_data = _load_deck_from_disk(source_job_id)
        if not source_data:
            raise ValueError(f"Source deck not found: {source_job_id}")

        art_theme        = req.art_theme        or source_data.get("theme", "")
        commander_prompt = req.commander_prompt or source_data.get("commander_prompt", "")
        user_name_rt     = req.user_name        or source_data.get("user_name", "")
        llm_model_rt     = req.llm_model        or source_data.get("llm_model")
        art_style        = source_data.get("art_style", "mtg_fantasy")
        model_speed      = source_data.get("model_speed", "quality")
        source_deck_slug = source_data.get("deck_slug", "")

        _push(job_id, "progress", json.dumps({
            "step": "deck",
            "msg":  f"Re-theming deck with Ollama: '{art_theme}'...",
        }))

        # ── Reconstruct raw card dicts for themer ─────────────────────────────
        # We feed the *original* MTG names back to the themer so it re-invents
        # names from scratch rather than theming already-themed names.
        def _stored_to_raw(d: dict) -> dict:
            return {
                "name":           d["original_name"],
                "mana_cost":      d.get("mana_cost", ""),
                "type_line":      d.get("type_line", ""),
                "oracle_text":    d.get("oracle_text", ""),   # may already be themed — OK
                "cmc":            d.get("cmc", 0),
                "color_identity": d.get("colors", []),
                "power":          d.get("power"),
                "toughness":      d.get("toughness"),
                "keywords":       [],
                "image_uris":     {"normal": d["scryfall_img"]} if d.get("scryfall_img") else {},
            }

        raw_commander = _stored_to_raw(source_data["commander"])
        raw_deck      = [_stored_to_raw(c) for c in source_data["deck"]]

        # ── Free ComfyUI VRAM before Ollama runs ──────────────────────────────
        if _art_lock.locked():
            _push(job_id, "progress", json.dumps({
                "step": "theme",
                "msg":  "⏳ Waiting for GPU — art gen in progress…",
            }))
            with _art_lock:
                pass
        # Free ComfyUI FLUX before Ollama loads for retheme — poll for confirmation.
        _push(job_id, "progress", json.dumps({"step": "theme", "msg": "Freeing GPU for Ollama…"}))
        _wait_for_comfyui_unload(job_id)

        # ── Re-run Ollama theming ─────────────────────────────────────────────
        _push(job_id, "progress", json.dumps({
            "step": "theme",
            "msg":  f"Theming cards with Ollama ({llm_model_rt or 'default'})…",
        }))
        themed_cmd: Optional[ThemedCard]       = None
        themed_deck: Optional[list[ThemedCard]] = None
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

            themed_cmd, themed_deck = themer.theme_deck(
                art_theme, raw_commander, raw_deck,
                commander_prompt=commander_prompt,
                progress_callback=_theme_cb,
                style_guide_hint=_style_meta["style_guide_hint"],
                themer_medium=_style_meta["themer_medium"],
                themer_quality=_style_meta["themer_quality"],
            )
            _push(job_id, "progress", json.dumps({"step": "theme", "msg": "Theming complete", "pct": 100}))
        except Exception as e:
            print(f"  [theme] OLLAMA THEMING ERROR (retheme): {e}")
            traceback.print_exc()
            _push(job_id, "progress", json.dumps({
                "step": "theme",
                "msg": f"[!] Ollama theming failed — falling back to plain card names. Error: {e}",
                "warning": True,
            }))
            # Don't raise — fall back to plain names like in _run_build
            themed_cmd = None
            themed_deck = None

        # Fallback to plain card names if theming failed
        if themed_cmd is None or themed_deck is None:
            def _plain(c): return ThemedCard(c["original_name"], c["original_name"], "", "", c)
            themed_cmd  = _plain(raw_commander)
            themed_deck = [_plain(c) for c in raw_deck]

        # ── Apply user name to commander ──────────────────────────────────────
        if user_name_rt and themed_cmd:
            themed_cmd.themed_name = _apply_user_name(themed_cmd.themed_name, user_name_rt)

        # ── Set symbol: reuse from source ─────────────────────────────────────
        render_out = RENDER_DIR / job_id / "cards"
        render_out.mkdir(parents=True, exist_ok=True)
        sym_path = RENDER_DIR / job_id / "set_symbol.png"

        old_sym = RENDER_DIR / source_job_id / "set_symbol.png"
        if old_sym.exists():
            _shutil.copy2(old_sym, sym_path)
            from PIL import Image as _PIL
            sym = _PIL.open(sym_path)
        else:
            sym = generate_set_symbol(art_theme, emblem_prompt=source_data.get("emblem_prompt", ""))
            sym.save(sym_path)

        # ── Locate existing raw art images ────────────────────────────────────
        # The raw FLUX outputs live in generated_art/{deck_slug}/{render_key}.png.
        # Build an art_paths dict (keyed by original_name) for render_deck_thumbnails.
        art_paths: dict[str, Optional[Path]] = {}
        if source_deck_slug:
            art_dir = Path("generated_art") / source_deck_slug
            for tc in [themed_cmd] + themed_deck:
                safe = "".join(ch if ch.isalnum() else "_" for ch in tc.original_name)[:48]
                p    = art_dir / f"{safe}.png"
                if p.exists():
                    art_paths[tc.original_name] = p

        art_found = sum(1 for v in art_paths.values() if v)
        _push(job_id, "progress", json.dumps({
            "step": "render",
            "msg":  f"Found {art_found} existing art image(s) — re-rendering card frames…",
        }))

        # ── Build result dict helper ──────────────────────────────────────────
        def _tc_to_dict(tc: ThemedCard, deck_index: int = 0, has_render: bool = False) -> dict:
            c    = tc.card
            safe = "".join(ch if ch.isalnum() else "_" for ch in tc.original_name)[:48]
            render_key = f"{safe}_{deck_index:03d}"
            oracle = _replace_card_self_ref(
                c.get("oracle_text", ""), tc.original_name, tc.themed_name
            )
            return {
                "original_name": tc.original_name,
                "themed_name":   tc.themed_name,
                "art_prompt":    tc.art_prompt,
                "flavor_text":   tc.flavor_text,
                "mana_cost":     c.get("mana_cost", ""),
                "type_line":     c.get("type_line", ""),
                "oracle_text":   oracle,
                "cmc":           c.get("cmc", 0),
                "colors":        c.get("color_identity", []),
                "power":         c.get("power"),
                "toughness":     c.get("toughness"),
                "scryfall_img":  (c.get("image_uris") or {}).get("normal", ""),
                "has_render":    has_render,
                "render_key":    render_key,
            }

        # ── Early checkpoint ──────────────────────────────────────────────────
        deck_json_path = RENDER_DIR / job_id / "deck.json"
        stats          = source_data.get("stats", {})
        checkpoint = {
            "status":           "rendering",
            "commander":        _tc_to_dict(themed_cmd, deck_index=0),
            "deck":             [_tc_to_dict(tc, deck_index=i) for i, tc in enumerate(themed_deck, 1)],
            "stats":            stats,
            "theme":            art_theme,
            "commander_prompt": commander_prompt,
            "emblem_prompt":    source_data.get("emblem_prompt", ""),
            "playstyle":        source_data.get("playstyle", ""),
            "bracket":          source_data.get("bracket", 3),
            "bracket_label":    source_data.get("bracket_label", ""),
            "art_style":        art_style,
            "model_speed":      model_speed,
            "generate_art":     source_data.get("generate_art", False),
            "deck_slug":        source_deck_slug,
            "face_key":         source_data.get("face_key", ""),
            "face_gender":      source_data.get("face_gender", "either"),
            "crew_key":         source_data.get("crew_key", ""),
            "crew_gender":      source_data.get("crew_gender", "either"),
            "user_name":        user_name_rt,
            "llm_model":        llm_model_rt or "",
            "border_theme":     source_data.get("border_theme", ""),
            "rethemed_from":    source_job_id,
            "built_at":         time.time(),
        }
        deck_json_path.write_text(json.dumps(checkpoint), encoding="utf-8")

        # ── Re-render card frames ─────────────────────────────────────────────
        _all_tcs_rt = [themed_cmd] + list(themed_deck)
        _oracle_ov_rt = {
            tc.original_name: _replace_card_self_ref(
                tc.card.get("oracle_text", ""), tc.original_name, tc.themed_name
            ) for tc in _all_tcs_rt
        }
        _flavor_ov_rt = {tc.original_name: tc.flavor_text or "" for tc in _all_tcs_rt}
        # Build render_keys mapping for indexed filenames
        _render_keys_rt = {}
        _render_keys_rt[themed_cmd.original_name] = f"{_safe_name(themed_cmd.original_name)}_000"
        for i, tc in enumerate(themed_deck, 1):
            _render_keys_rt[tc.original_name] = f"{_safe_name(tc.original_name)}_{i:03d}"
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
        result["commander"] = _tc_to_dict(themed_cmd, deck_index=0, has_render=themed_cmd.original_name in saved_imgs)
        result["deck"]      = [_tc_to_dict(tc, deck_index=i, has_render=tc.original_name in saved_imgs) for i, tc in enumerate(themed_deck, 1)]
        _jobs[job_id].update(result)
        deck_json_path.write_text(json.dumps(result), encoding="utf-8")

        _push(job_id, "done", json.dumps({"job_id": job_id}))

    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"]  = str(e)
        _push(job_id, "error", json.dumps({"msg": str(e)}))
        traceback.print_exc()
    finally:
        _jobs.get(job_id, {}).pop("cancel_event", None)
        msgs = _progress.get(job_id)
        if msgs and len(msgs) > 80:
            _progress[job_id] = msgs[-80:]
        _trim_in_memory_jobs()


# ── Memory hygiene ────────────────────────────────────────────────────────────
_MAX_INMEM_JOBS = 6   # keep last N full job payloads in RAM; older fall to disk

def _trim_in_memory_jobs():
    """Evict old completed jobs' card payloads from memory. Status stays so
    /events and /status still work without re-reading disk."""
    done = [(jid, j) for jid, j in _jobs.items() if j.get("status") in ("done", "error")]
    if len(done) <= _MAX_INMEM_JOBS:
        return
    # Sort by built_at if present, else by insertion order
    done.sort(key=lambda kv: kv[1].get("built_at", 0))
    for jid, _ in done[: len(done) - _MAX_INMEM_JOBS]:
        # Keep just enough metadata for status/events endpoints
        j = _jobs[jid]
        _jobs[jid] = {
            "status":   j.get("status", "done"),
            "error":    j.get("error"),
            "built_at": j.get("built_at"),
        }
        # Free progress events for these old jobs too
        _progress.pop(jid, None)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.post("/api/commander/search")
async def search_commander(req: SearchRequest):
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
    }


@app.get("/api/commander/autocomplete")
async def autocomplete_commander(q: str = ""):
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
    for p in sorted(RENDER_DIR.glob("*/deck.json"),
                    key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data   = json.loads(p.read_text(encoding="utf-8"))
            job_id = p.parent.name
            status = data.get("status", "done")
            # Skip purely in-memory building jobs that haven't checkpointed yet
            if status not in ("done", "rendering"):
                continue
            cmd    = data.get("commander", {})
            # Thumbnail: prefer rendered commander art, fall back to scryfall
            thumb = None
            rkey  = cmd.get("render_key")
            if rkey and (p.parent / "cards" / f"{rkey}.png").exists():
                thumb = f"/api/deck/{job_id}/card-image/{rkey}"
            elif cmd.get("scryfall_img"):
                thumb = cmd["scryfall_img"]
            results.append({
                "job_id":           job_id,
                "commander_name":   cmd.get("original_name", ""),
                "themed_name":      cmd.get("themed_name", ""),
                "theme":            data.get("theme", ""),
                "commander_prompt": data.get("commander_prompt", ""),
                "bracket":          data.get("bracket", 0),
                "bracket_label":    data.get("bracket_label", ""),
                "card_count":       len(data.get("deck", [])) + 1,
                "built_at":         data.get("built_at"),
                "thumbnail":        thumb,
                "partial":          status == "rendering",
                "is_copy":          bool(data.get("is_copy")),
                "copied_from":      data.get("copied_from", ""),
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


@app.post("/api/deck/build")
async def build_deck(req: BuildRequest, background_tasks: BackgroundTasks, request: Request):
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
    # Rate limiting: prevent request floods
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip, _RATE_LIMIT_BUILD_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_BUILD_REQUESTS} builds per {_RATE_LIMIT_WINDOW}s")

    # Verify the source deck actually exists (either in memory or on disk)
    source_ok = (
        (job_id in _jobs and _jobs[job_id].get("status") in ("done", "rendering"))
        or (RENDER_DIR / job_id / "deck.json").exists()
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
    # Rate limiting: prevent request floods
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip, _RATE_LIMIT_BUILD_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_BUILD_REQUESTS} builds per {_RATE_LIMIT_WINDOW}s")

    if not req.cards:
        raise HTTPException(400, "No cards specified")
    source_ok = (
        (job_id in _jobs and _jobs[job_id].get("status") in ("done", "rendering"))
        or (RENDER_DIR / job_id / "deck.json").exists()
    )
    if not source_ok:
        raise HTTPException(404, f"Source deck not found: {job_id}")

    new_job_id = uuid.uuid4().hex[:16]
    _jobs[new_job_id]     = {"status": "queued", "cancel_event": threading.Event(), "created_at": time.time()}
    _progress[new_job_id] = []
    background_tasks.add_task(_run_regen_cards, new_job_id, job_id, req)
    return {"job_id": new_job_id}


@app.post("/api/deck/{job_id}/retheme")
async def retheme_deck(job_id: str, req: RethemeRequest, background_tasks: BackgroundTasks):
    """
    Re-run Ollama theming for an existing deck without regenerating art.

    Returns a new job_id.  The client can watch progress on
    ``/api/deck/{new_job_id}/events`` and navigate to the new deck when done.
    """
    source_ok = (
        (job_id in _jobs and _jobs[job_id].get("status") in ("done", "rendering"))
        or (RENDER_DIR / job_id / "deck.json").exists()
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
    import shutil as _shutil

    src_dir  = RENDER_DIR / job_id
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
    dst_dir    = RENDER_DIR / new_job_id

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

    # Refuse to delete an actively-building deck
    job = _jobs.get(job_id, {})
    if job.get("status") == "building":
        raise HTTPException(409, "Cannot delete a deck that is currently building")

    # Remove render directory from disk
    deck_dir = RENDER_DIR / job_id
    if deck_dir.exists():
        try:
            _shutil.rmtree(str(deck_dir))
        except Exception as e:
            raise HTTPException(500, f"Failed to remove deck directory: {e}")

    # Remove generated_art directory for this job if it exists
    for art_dir in Path("generated_art").glob(f"*_{job_id[:8]}"):
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

        deck_dir = RENDER_DIR / job_id
        if deck_dir.exists():
            try:
                _shutil.rmtree(str(deck_dir))
            except Exception:
                skipped.append(job_id)
                continue

        for art_dir in Path("generated_art").glob(f"*_{job_id[:8]}"):
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
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")
    return StreamingResponse(
        _sse_stream(job_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Keys on _jobs[job_id] that are internal-only and must NEVER appear in a
# JSON response — they're not serializable (threading primitives) or they're
# implementation detail the client has no business seeing.
_INTERNAL_JOB_KEYS = {"cancel_event"}

def _serializable_job(job: dict) -> dict:
    """Return a JSON-safe shallow copy of a job dict (strips threading.Event etc.)."""
    return {k: v for k, v in job.items() if k not in _INTERNAL_JOB_KEYS}


def _load_deck_from_disk(job_id: str) -> Optional[dict]:
    """Load a completed deck from disk — used after server restarts.

    A deck.json written with status="rendering" means art-gen was in flight
    when the server was killed.  The deck data is valid; we just lack some
    rendered card images.  Normalise to "done" so the deck is loadable.
    """
    p = RENDER_DIR / job_id / "deck.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("status") == "rendering":
                data["status"] = "done"
                # Persist the corrected status so future reads are consistent.
                try:
                    p.write_text(json.dumps(data), encoding="utf-8")
                except Exception:
                    pass
            return data
        except Exception:
            return None
    return None


@app.get("/api/deck/{job_id}/status")
async def deck_status(job_id: str):
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
    job = _jobs.get(job_id)
    if not job:
        disk = _load_deck_from_disk(job_id)
        if disk:
            _jobs[job_id] = disk
            job = disk
        else:
            raise HTTPException(404, "Job not found")
    # Accept any state that has a usable payload — done, cancelled mid-build,
    # or rendering. The client gets the partial deck plus a status flag so it
    # can show what was completed instead of a 409 dead-end.
    if job["status"] == "building":
        raise HTTPException(409, "Deck still building — listen on /events instead")
    if job["status"] == "error":
        raise HTTPException(409, f"Deck failed: {job.get('error', 'unknown error')}")
    # "done", "rendering", "cancelled" → return whatever we have on disk
    return _serializable_job(job)


@app.get("/api/deck/{job_id}/card-image/{render_key}")
async def card_image(job_id: str, render_key: str):
    cards_dir = RENDER_DIR / job_id / "cards"
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
    raise HTTPException(404, "Card image not found")


@app.get("/api/deck/{job_id}/set-symbol")
async def set_symbol_endpoint(job_id: str):
    path = RENDER_DIR / job_id / "set_symbol.png"
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
async def face_method():
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
async def comfy_status():
    """
    Lightweight ComfyUI readiness probe for the UI.  Returns the same dict
    shape used by the build pre-flight so the frontend can warn the user
    before they kick off a long build that would otherwise fall back to
    Scryfall art on every card.
    """
    return ImageGen.health_check()


@app.get("/api/llm-models")
async def get_llm_models():
    """
    Return the curated LLM catalog with per-entry installed status.
    The UI uses this to populate the model selector in StepTheme.
    Entries flagged installed=False are shown disabled with a pull hint.
    """
    from themer import list_available_llms
    return list_available_llms()


@app.get("/api/art-styles")
async def get_art_styles():
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
        result.append({
            "key":         key,
            "label":       preset["label"],
            "description": preset["description"],
            "icon":        preset["icon"],
            "ready":       all_inst,
            "partial":     any_inst and not all_inst,
            "loras":       loras,
            "custom":      key in custom_keys,
            # Include full config so the UI can pre-populate the editor
            "flux_prefix":      preset.get("flux_prefix") or "",
            "negative_prompt":  preset.get("negative_prompt", ""),
            "style_guide_hint": preset.get("style_guide_hint", ""),
            "themer_medium":    preset.get("themer_medium", ""),
            "themer_quality":   preset.get("themer_quality", ""),
        })
    return result


@app.get("/api/comfyui/loras")
async def list_comfyui_loras():
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

    upsert_custom_preset(key, preset)
    return {"ok": True, "key": key}


@app.delete("/api/art-styles/custom/{key}")
async def delete_custom_art_style(key: str):
    """Remove a custom art style preset."""
    from image_gen import delete_custom_preset, _LORA_PRESETS
    if key in _LORA_PRESETS:
        raise HTTPException(400, f"'{key}' is a built-in preset and cannot be deleted.")
    deleted = delete_custom_preset(key)
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

@app.get("/api/deck/{job_id}/export/zip")
async def export_zip(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "done":
        raise HTTPException(409, f"Deck not ready — status: {job['status']}")
    render_dir = RENDER_DIR / job_id
    try:
        data = build_zip(job["commander"], job["deck"], render_dir)
    except Exception as e:
        raise HTTPException(500, f"ZIP export failed: {e}")
    safe = "".join(c if c.isalnum() else "_" for c in job["commander"]["original_name"])[:30]
    filename = f"{safe}_deck.zip"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/deck/{job_id}/export/pdf")
async def export_pdf(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "done":
        raise HTTPException(409, f"Deck not ready — status: {job['status']}")
    render_dir = RENDER_DIR / job_id
    try:
        data = build_pdf(job["commander"], job["deck"], render_dir)
    except Exception as e:
        raise HTTPException(500, f"PDF export failed: {e}")
    safe = "".join(c if c.isalnum() else "_" for c in job["commander"]["original_name"])[:30]
    filename = f"{safe}_proxies.pdf"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Serve React frontend ───────────────────────────────────────────────────────
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        index = STATIC_DIR / "index.html"
        return FileResponse(index)


# ── Dev entry ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("Starting Commander Deck Builder API...")
    print("  API:      http://localhost:8000/api/")
    print("  Frontend: http://localhost:8000/")
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
