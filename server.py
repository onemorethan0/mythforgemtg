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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional, List

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
from pydantic import BaseModel, Field, validator

# ── Local modules ─────────────────────────────────────────────────────────────
from scryfall_client    import ScryfallClient
import deck_import
from commander_analysis import build_commander_profile
from deck_builder       import DeckBuilder, compute_stats, aggregate_duplicates
from collection         import (
    load_owned_names, owned_count, suite_collection_path,
    load_collection, add_card as coll_add_card, set_count as coll_set_count,
    remove_card as coll_remove_card, bulk_import as coll_bulk_import, owned_key,
)
from playstyle          import (
    PLAYSTYLES, PLAYSTYLE_ORDER, resolve_themes, get_slot_adjustments,
)
from themer             import Themer, ThemedCard, ThemingCancelled
from image_gen          import ImageGen, GenSettings, _is_flux, _is_sd35, _is_sdxl, _is_krea, _is_qwen
import card_renderer
from card_renderer      import render_card, render_deck_thumbnails
from set_symbol         import generate_set_symbol
import mana_pips
from exporter           import build_zip, build_pdf, build_video_zip
from bracket            import BRACKET_LABELS
from face_ref           import get_face_paths
from model3d            import Model3DGen, generate_commander_3d

# ── In-memory log capture ──────────────────────────────────────────────────────
# Tee stdout/stderr into a bounded ring buffer so the running server's output
# (startup checks, pipeline prints, tracebacks, uvicorn access logs) can be
# viewed from inside the app via /api/logs — regardless of how the process was
# launched (console, redirected file, or detached with no console at all).
import sys as _sys
import collections
from datetime import datetime as _dt

_LOG_BUFFER: "collections.deque[str]" = collections.deque(maxlen=5000)


class _TeeStream:
    """Write-through stream wrapper that mirrors output into _LOG_BUFFER line by line."""

    def __init__(self, original):
        self._original = original
        self._partial = ""

    def write(self, text):
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass
        self._partial += text
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            _LOG_BUFFER.append(f"{_dt.now().strftime('%H:%M:%S')} {line}")
        return len(text)

    def flush(self):
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass

    def isatty(self):
        # uvicorn's log formatter calls this during config; guard against a
        # None/detached stdout so logging setup never crashes on launch.
        try:
            return bool(self._original) and self._original.isatty()
        except Exception:
            return False

    def __getattr__(self, name):
        return getattr(self._original, name)


# Wrap whatever stdout/stderr are at this point (model3d already installed a
# UTF-8 wrapper on import). Wrapping happens before uvicorn.run() so uvicorn's
# log handlers bind to the tee and access logs are captured too.
_sys.stdout = _TeeStream(_sys.stdout)
_sys.stderr = _TeeStream(_sys.stderr)


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
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

STATIC_DIR  = Path(__file__).parent / "frontend" / "dist"
# Anchor to the script location, not the cwd — the server (and deck history)
# must work the same regardless of where it's launched from.
RENDER_DIR  = Path(__file__).parent / "renders"
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

# Serializes ComfyUI auto-start so the startup thread and concurrent builds never
# spawn duplicate ComfyUI processes (each re-checks "is it up?" inside the lock).
_comfyui_start_lock = threading.Lock()

# Per-source-deck lock to serialize regen-cards writes to the same deck dir.
# Without this, two concurrent regen calls on the same deck race their PNG
# writes and SSE card_ready events.
_deck_regen_locks: dict[str, threading.Lock] = {}
_deck_regen_locks_meta_lock = threading.Lock()

# 3D generation job store (separate from main _jobs to keep payloads small)
_3d_jobs: dict[str, dict] = {}
_3d_progress: dict[str, list[str]] = {}   # job_3d_id → list of SSE event strings

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


def _ensure_frontend_built():
    """Check if frontend needs rebuilding and rebuild if necessary.

    Compares modification times of frontend source (src/) and built output (dist/).
    If any source file is newer than the build, trigger a rebuild.
    """
    import subprocess
    import sys

    frontend_dir = Path(__file__).parent / "frontend"
    src_dir = frontend_dir / "src"
    dist_dir = frontend_dir / "dist"

    if not src_dir.exists():
        print("  [startup] [!] Frontend source not found (frontend/src/)", flush=True)
        return

    if not dist_dir.exists():
        print("  [startup] [!] Frontend dist not found — rebuilding...", flush=True)
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "npm"] if sys.platform == "win32" else None,
                check=False, cwd=frontend_dir
            )
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=frontend_dir,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                print("  [startup] [OK] Frontend built successfully", flush=True)
            else:
                print(f"  [startup] [X] Frontend build failed: {result.stderr[:200]}", flush=True)
        except Exception as e:
            print(f"  [startup] [X] Frontend build error: {e}", flush=True)
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
            try:
                result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=frontend_dir,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.returncode == 0:
                    print("  [startup] [OK] Frontend rebuilt successfully", flush=True)
                else:
                    print(f"  [startup] [X] Frontend build failed: {result.stderr[:200]}", flush=True)
            except subprocess.TimeoutExpired:
                print("  [startup] [X] Frontend build timed out (>120s)", flush=True)
            except Exception as e:
                print(f"  [startup] [X] Frontend build error: {e}", flush=True)
        else:
            print("  [startup] [OK] Frontend is up to date", flush=True)
    except Exception as e:
        print(f"  [startup] [!] Could not check frontend build status: {e}", flush=True)


# ── LLM backend checks (startup) ───────────────────────────────────────────────

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


# ── Request / Response models ─────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str


class GenSettingsModel(BaseModel):
    """User-configurable generation knobs from the frontend Advanced panels.
    Mirrors image_gen.GenSettings; all optional so omitting it preserves defaults."""
    guidance:       Optional[float] = None   # FLUX FluxGuidance (1.5–5)
    steps:          Optional[int]   = None   # sampler steps
    sampler:        Optional[str]   = None
    scheduler:      Optional[str]   = None
    seed_mode:      Optional[str]   = None   # "random" | "fixed"
    seed:           Optional[int]   = None
    lora_overrides: Optional[List[dict]] = None  # [{filename, model_strength, clip_strength?, trigger?}]
    style_variant:  Optional[str]   = None   # pin a preset rotation flavor deck-wide ("" / "auto" = Variety mix)
    face_method:    Optional[str]   = None   # None=auto | "reactor" | "pulid_flux" | "none"
    face_weight:    Optional[float] = None
    safe_mode:      Optional[bool]  = None
    enhance:        Optional[bool]  = None   # Perturbed-Attention Guidance (better anatomy; ~2x slower)
    face_fix:       Optional[bool]  = None   # FaceDetailer pass (SDXL/Illustrious; re-renders faces)


def _resolve_gen_settings(gs: "Optional[GenSettingsModel]") -> GenSettings:
    """Convert the API GenSettingsModel into the image_gen.GenSettings dataclass.
    None / missing fields fall back to defaults (existing behavior)."""
    if gs is None:
        return GenSettings()
    try:
        d = gs.model_dump(exclude_none=True)   # pydantic v2
    except AttributeError:
        d = {k: v for k, v in gs.dict().items() if v is not None}  # pydantic v1
    return GenSettings.from_dict(d)


def _gen_settings_to_dict(gs: "Optional[GenSettingsModel]") -> dict:
    """Serialize a request GenSettingsModel to a plain (None-stripped) dict for
    persistence in deck.json, so regen paths can recover the user's advanced
    settings — guidance/steps/lora_overrides and a pinned style_variant."""
    if gs is None:
        return {}
    try:
        return gs.model_dump(exclude_none=True)   # pydantic v2
    except AttributeError:
        return {k: v for k, v in gs.dict().items() if v is not None}  # pydantic v1


def _resolve_gen_settings_reusing(gs: "Optional[GenSettingsModel]",
                                  source_data: "Optional[dict]") -> GenSettings:
    """For regen paths (rebuild / regen-cards / retheme): honor the request's
    gen_settings when provided, else fall back to the gen_settings persisted in the
    source deck.json. This keeps a pinned style_variant (and every other advanced
    knob) alive across a re-generation instead of silently resetting to defaults."""
    if gs is not None:
        return _resolve_gen_settings(gs)
    stored = (source_data or {}).get("gen_settings") or None
    return GenSettings.from_dict(stored)


class BuildRequest(BaseModel):
    # Optional when importing an existing decklist (deck_url / deck_list provide
    # the commander). Required for the generate-a-deck path.
    commander_name:    str = Field("", max_length=120)
    # Import an existing deck instead of generating one. deck_url = a Moxfield/
    # Archidekt URL; deck_list = pasted decklist text. When either is set the
    # 99-card generator is skipped and the imported list is themed/rendered.
    deck_url:          str = Field("", max_length=600)
    deck_list:         str = Field("", max_length=20000)
    playstyle:         str = "auto"
    # Caps prevent long appearance dumps from polluting the LLM batch prompt and
    # blowing FLUX's first-N-token attention window (causes "standing portrait"
    # output with no card action).  Cap raised from 400: art_theme is now a
    # back-compat fallback (the structured theme_spec is the primary input) and is
    # persisted/restored, so it must hold the composed structured brief without
    # truncating (a long Setting + all chips can exceed 800; build_creative_brief
    # caps the actual prompt seed at 900 chars regardless).
    art_theme:         str = Field("", max_length=2000)
    commander_prompt:  str = Field("", max_length=500)
    emblem_prompt:     str = Field("", max_length=300)
    art_style:         str = "mtg_fantasy"  # LoRA preset key
    generate_art:      bool = False
    model_speed:       str  = "quality"  # "quality" (flux-dev) or "fast" (flux-schnell) or "sd35" (SD 3.5 Large)
    checkpoint:        Optional[str] = None   # explicit checkpoint filename; None = auto-detect from ComfyUI
    bracket:           int  = 3
    face_key:          Optional[str] = None   # commander face photos
    face_gender:       str = "either"         # "male", "female", or "either"
    crew_key:          Optional[str] = None   # crew face photos for creature cards
    crew_gender:       str = "either"         # gender hint for crew faces
    crew_prompt:       str = ""               # shared appearance notes for crew-faced creatures
    is_commander_deck: bool = True            # False → imported non-Commander list: no auto hero face
    face_assignments:  Optional[dict] = None  # {card original_name: crew-photo index} — explicit per-card faces (non-commander decks)
    user_name:         Optional[str] = None   # replaces the commander's generated first name
    llm_model:         Optional[str] = None   # Ollama model key — None = use themer default
    border_theme:      str           = ""     # free-text description of card-border decoration
    frame_style:       str           = "builtin"  # "builtin" (bundled frames) or "m15" (official-style, needs local Card Conjurer)
    commander_tribe:   str           = ""     # override creature tribe to reskin; "" = auto-detect
    custom_pips:       bool          = False  # themed 2-colour mana pips (disc + black silhouette)
    # Two-phase flow: a decklist generated up front (POST /api/deck/generate-list)
    # is passed back here so the build skips DeckBuilder and themes/renders this
    # exact list. tribal_overrides = user-chosen {OriginalType: Replacement} from
    # the theme step's per-tribe fields (multi-tribe reskin; wins over auto-detect).
    prebuilt_deck:     Optional[list] = None
    tribal_overrides:  Optional[dict] = None
    # "Auto-theme creature types" checkbox: auto-generate ONE theme-fitting
    # replacement for EVERY deck creature type (not just the commander's) and
    # apply it uniformly. Explicit tribal_overrides still win per-type. Defaults
    # ON — a build with no directive gets cohesive theme-fitting creature types.
    auto_theme_tribes: bool          = True
    # Collection-aware building (Myth Suite C4): when true, the 99-card generator
    # PREFERS cards from the user's owned-collection export
    # (Documents/MythSuite/collection.csv), falling back to unowned EDHREC picks
    # when the collection can't cover a slot. Generate path only (imports ignore it).
    use_collection:    bool          = False
    # Structured "deck vision" fields (setting/moods/genres/lighting/inspiration).
    # Now the PRIMARY theming input: themer.build_creative_brief() reads these as
    # distinct labelled dimensions (not the flattened art_theme blob). Persisted so
    # Edit can restore them.
    theme_spec:        Optional[dict] = None
    # Creativity dial — how much invented detail the creative brief adds on top of
    # the user's stated motifs: "faithful" | "balanced" | "imaginative".
    creativity:        str           = "balanced"
    gen_settings:      Optional[GenSettingsModel] = None   # Advanced-panel overrides


class RebuildRequest(BaseModel):
    """Minimal params needed to re-run art gen for an already-themed deck."""
    art_style:   str = "mtg_fantasy"
    model_speed: str = "quality"
    checkpoint:  Optional[str] = None   # explicit checkpoint; None = auto-detect
    face_key:    Optional[str] = None
    face_gender: str = "either"
    crew_key:    Optional[str] = None
    crew_gender: str = "either"
    crew_prompt: Optional[str] = None   # None → use saved crew_prompt
    gen_settings: Optional[GenSettingsModel] = None


class CardRegenEntry(BaseModel):
    render_key:    str            # safe-name used in the filename / URL
    original_name: str            # canonical MTG card name for lookup fallback
    custom_prompt: Optional[str] = None   # user's custom text (stored separately; never clobbers art_prompt)
    use_custom:    bool = False           # True → feed custom_prompt to generation; False → use LLM art_prompt


class RegenCardsRequest(BaseModel):
    """Per-card regeneration — re-run art gen for a specific subset of cards."""
    cards:       List[CardRegenEntry]
    art_style:   str = "mtg_fantasy"
    model_speed: str = "quality"
    checkpoint:  Optional[str] = None   # explicit checkpoint; None = auto-detect
    face_key:    Optional[str] = None   # commander face override
    face_gender: str = "either"
    crew_key:    Optional[str] = None   # crew faces override for creature cards
    crew_gender: str = "either"
    # Force a single uploaded face onto EVERY selected card, bypassing the
    # commander/humanoid-creature routing. Lets the user drop a friendly face
    # onto any card they picked (even non-humanoid ones) and regenerate it.
    force_face_key:    Optional[str] = None
    force_face_gender: str = "either"
    gen_settings: Optional[GenSettingsModel] = None


class AnimateCardEntry(BaseModel):
    render_key:    str
    original_name: str


class AnimateCardsRequest(BaseModel):
    """Animate a subset of cards — I2V the art and/or overlay a procedural foil
    sheen, recomposite, and encode a looping clip (mp4 / webp / gif)."""
    cards:         List[AnimateCardEntry]
    motion_preset: str = "subtle"
    motion_prompt: Optional[str] = None   # free-text custom motion (wins over motion_preset)
    motion_strength: Optional[float] = None  # 0..1 how much the art moves (LTXV); None → default 0.5
    loop:          bool = True
    loop_style:    Optional[str] = None   # crossfade | bounce | off (motion); None → crossfade
    duration:      Optional[float] = None  # desired clip length (seconds); → frame count (snapped for I2V)
    frames:        Optional[int] = None   # explicit frame-count override (wins over duration)
    fps:           Optional[int] = None
    method:        Optional[str] = None   # override the auto-detected I2V model
    effect:        str = "motion"         # motion | foil | motion_foil
    foil_style:    str = "holo"           # holo | gold | silver (when effect uses foil)
    foil_intensity: Optional[float] = None  # foil sheen strength 0..1 (default ~0.55)
    fmt:           str = "mp4"            # mp4 | webp | gif (output container)


class RethemeRequest(BaseModel):
    """Re-run Ollama theming for an already-built deck, keeping all existing card art."""
    art_theme:        Optional[str] = None   # None → use saved theme from deck.json
    commander_prompt: Optional[str] = None   # None → use saved commander_prompt
    user_name:        Optional[str] = None   # None → use saved user_name
    llm_model:        Optional[str] = None   # None → use saved llm_model
    commander_tribe:  Optional[str] = None   # None → use saved / auto-detect
    theme_spec:       Optional[dict] = None  # None → use saved structured theme_spec
    creativity:       Optional[str]  = None  # None → use saved creativity dial


class SingleCardModel(BaseModel):
    """A user-authored custom card definition for single-card mode."""
    name:        str = Field("", max_length=160)
    mana_cost:   str = Field("", max_length=80)   # e.g. "{2}{W}{U}"
    type_line:   str = Field("", max_length=160)  # e.g. "Legendary Creature — Knight"
    oracle_text: str = Field("", max_length=2000)
    flavor_text: str = Field("", max_length=600)
    power:       Optional[str] = None             # strings so "*"/"1+*" are allowed
    toughness:   Optional[str] = None
    loyalty:     Optional[str] = None             # planeswalkers
    rarity:      str = "rare"                     # common|uncommon|rare|mythic|special
    colors:      Optional[List[str]] = None       # WUBRG; None → derive from mana_cost


class CardBuildRequest(BaseModel):
    """Single custom card → theme + (optional) art + rendered proxy. Reuses the
    deck theming/art knobs; the result persists as a 'deck of one' so every
    existing per-card action (regen/animate/3D/export/history) works on it."""
    card:             SingleCardModel
    # Theming
    theme_mode:       str = "author"   # "author" (keep my name/text; AI art only) | "full" (AI themes/renames)
    art_prompt_mode:  str = "auto"     # "auto" (LLM writes art prompt) | "custom" (user supplies it)
    art_prompt:       str = Field("", max_length=2000)   # used when art_prompt_mode == "custom"
    art_theme:        str = Field("", max_length=2000)
    theme_spec:       Optional[dict] = None
    creativity:       str = "balanced"
    commander_prompt: str = Field("", max_length=500)    # subject appearance
    emblem_prompt:    str = Field("", max_length=300)
    # Art / render
    art_style:        str = "mtg_fantasy"
    generate_art:     bool = False
    model_speed:      str  = "quality"
    checkpoint:       Optional[str] = None
    llm_model:        Optional[str] = None
    border_theme:     str = ""
    frame_style:      str = "builtin"
    custom_pips:      bool = False
    # Face conditioning (single likeness)
    face_key:         Optional[str] = None
    face_gender:      str = "either"
    gen_settings:     Optional[GenSettingsModel] = None


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

_VRAM_FLUX_REQUIRED_GB  = 16.0   # minimum FREE VRAM before loading FLUX+LoRAs (system-wide)
                                  # Peak load: FLUX fp8 UNet ~8.5 GB + T5 ~4.7 GB + LoRAs
                                  # + ReActor + overhead ≈ 18 GB peak during conditioning.
                                  # After Ollama (9.89 GB) evicts: ~21 GB free → passes ✓
                                  # While Ollama still loaded: ~11 GB free → blocks ✓
                                  # NOTE: now measured by nvidia-smi (system-wide), not
                                  # ComfyUI's internal pool which was blind to Ollama.
_VRAM_LLM_CLEAR_GB      = 14.0   # target free VRAM after ComfyUI /free before the LLM loads
                                  # After FLUX unloads: ~21-22 GB free, threshold met ✓
                                  # qwen3:14b needs ~10 GB; 14 GB gives 4 GB headroom
_EVICT_POLL_INTERVAL    = 3.0    # seconds between VRAM polls (increased from 2.0 for efficiency)
_EVICT_MAX_WAIT         = 120    # seconds — large models (27B, 23 GB) need up to 60 s


def _comfyui_vram_free_gb() -> Optional[float]:
    """Return actual free GPU VRAM in GB, system-wide (all processes).

    Uses nvidia-smi as the authoritative source because ComfyUI's /system_stats
    vram_free only reflects ComfyUI's own CUDA allocation pool — it is blind to
    VRAM held by other processes (e.g. Ollama holding ~10 GB).  Using nvidia-smi
    prevents false-green VRAM gates that schedule FLUX while Ollama is still
    resident, causing OOM crashes on the RTX 3090.

    Falls back to ComfyUI's internal view if nvidia-smi is unavailable.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            free_mib = int(result.stdout.strip().split("\n")[0].strip())
            return free_mib / 1024.0   # MiB → GB
    except Exception:
        pass

    # Fallback: ComfyUI's internal view (unreliable when Ollama is also loaded)
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

    # Use the LLM-clear threshold here: after unloading FLUX we want plenty
    # of headroom for the LLM that's about to load.
    return _wait_for_vram(_VRAM_LLM_CLEAR_GB, job_id=job_id, label="ComfyUI unload")


def _ollama_loaded_models() -> list[str]:
    """Return ids of currently-loaded LLM models (backend-aware).

    • llama.cpp → llama-swap GET /running (defensive parse of its JSON).
    • Ollama    → GET /api/ps.
    Returns [] if nothing loaded or the backend is unreachable. Used only as an
    optimization hint to skip eviction work when the LLM isn't holding VRAM.
    """
    from themer import LLM_BACKEND, LLM_BASE
    try:
        if LLM_BACKEND == "llamacpp":
            r = requests.get(f"{LLM_BASE}/running", timeout=4)
            if r.status_code != 200:
                return []
            data = r.json()
            items = data.get("running", data) if isinstance(data, dict) else data
            out = []
            for it in (items or []):
                if isinstance(it, dict):
                    mid = it.get("model") or it.get("id") or it.get("name")
                    if mid:
                        out.append(mid)
                elif isinstance(it, str):
                    out.append(it)
            return out
        r = requests.get("http://127.0.0.1:11434/api/ps", timeout=4)
        if r.status_code == 200:
            return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


def _wait_for_ollama_evict(model: str, job_id: str = "") -> bool:
    """
    Evict the LLM from VRAM, then confirm free VRAM >= _VRAM_FLUX_REQUIRED_GB
    before FLUX loads. Backend-aware:

      • llama.cpp → POST llama-swap /api/models/unload (the upstream process
        exits, releasing VRAM cleanly), then poll nvidia-smi for free VRAM.
      • Ollama    → keep_alive=0 then a TWO-STAGE confirmation (process list
        drop, then physical VRAM), because Ollama can report a model unloaded
        while CUDA still holds the pages cached (the historic OOM crash cause).

    Fast-path: if VRAM is already sufficient, skip all eviction work. This
    avoids dead POST timeouts on rebuild/regen jobs where the LLM was never
    used in this session.
    """
    from themer import LLM_BACKEND, LLM_BASE

    # Fast-path: check VRAM first (cheap, single call). If we already have
    # enough headroom there's nothing to evict — don't even hit the backend.
    free_now = _comfyui_vram_free_gb()
    if free_now is not None and free_now >= _VRAM_FLUX_REQUIRED_GB:
        if job_id:
            print(f"  [vram] LLM evict skipped — VRAM already clear "
                  f"({free_now:.1f} GB free, need {_VRAM_FLUX_REQUIRED_GB:.0f}+)")
        return True

    # ── llama.cpp / llama-swap branch ──
    if LLM_BACKEND == "llamacpp":
        running = _ollama_loaded_models()
        if not running:
            # LLM not resident — the VRAM pressure (if any) is ComfyUI's own
            # FLUX models, which is exactly where we want them. Proceed.
            if job_id:
                free_s = f"{free_now:.1f}" if free_now is not None else "?"
                print(f"  [vram] LLM not loaded — ComfyUI models resident "
                      f"({free_s} GB free). Proceeding to generation.")
            return True
        try:
            requests.post(f"{LLM_BASE}/api/models/unload", timeout=10)
        except Exception:
            pass
        ok = _wait_for_vram(_VRAM_FLUX_REQUIRED_GB, job_id=job_id,
                            label=f"post-LLM unload ({','.join(running)})")
        if job_id:
            print(f"  [vram] {'[OK]' if ok else '[!]'} llama-swap unload "
                  f"{'confirmed' if ok else 'did not fully clear VRAM'}")
        return ok

    # ── Ollama branch (legacy two-stage) ──
    # VRAM is tight — check if anything is actually loaded before sending
    # keep_alive=0.  If Ollama is idle/offline, skip the POST requests (each
    # has a 10 s timeout that adds dead wait before FLUX can start).
    loaded_now = _ollama_loaded_models()
    model_base = model.split(":")[0]
    model_is_loaded = any(model_base in m for m in loaded_now)

    if not model_is_loaded and not loaded_now:
        # Ollama not loaded — nothing to evict.  VRAM pressure (if any) comes from
        # ComfyUI's own resident models (NORMAL_VRAM keeps FLUX in VRAM between jobs).
        # That's exactly where we want FLUX — do NOT wait for it to disappear.
        # ComfyUI is already ready to accept the next generation job.
        if job_id:
            free_v = _comfyui_vram_free_gb()
            free_s = f"{free_v:.1f}" if free_v is not None else "?"
            print(f"  [vram] Ollama not loaded — ComfyUI models resident "
                  f"({free_s} GB free). Proceeding to generation.")
        return True

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
    cards_dir = RENDER_DIR / job_id / "cards"
    rendered = {fp.stem for fp in cards_dir.glob("*.png")} if cards_dir.exists() else set()

    def _has(tc: ThemedCard, idx: int) -> bool:
        return f"{_safe_name(tc.original_name)}_{idx:03d}" in rendered

    path = RENDER_DIR / job_id / "deck.json"
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
        "rarity":         d.get("rarity", ""),
        "quantity":       d.get("quantity", 1),
        "image_uris":     {"normal": d["scryfall_img"]} if d.get("scryfall_img") else {},
    }


_MANA_SYMBOL_RE = re.compile(r"\{([^}]+)\}")
_WUBRG = ("W", "U", "B", "R", "G")


def _parse_mana_cost(mana_cost: str) -> tuple[float, list[str]]:
    """Derive (cmc, color_identity) from a mana-cost string like '{2}{W}{U}'.

    Generic numbers add to cmc; X = 0; hybrid/phyrexian symbols (e.g. {W/U},
    {2/W}, {W/P}) count 1 toward cmc and contribute every WUBRG colour they name.
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
        cmc += 1   # any non-generic symbol (incl. hybrids) costs 1
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
    cmc, derived_colors = _parse_mana_cost(m.mana_cost)
    colors = [c.upper() for c in (m.colors or []) if c] or derived_colors
    name = (m.name or "").strip() or "Custom Card"
    rarity = (m.rarity or "rare").strip().lower()
    return {
        "name":               name,
        "mana_cost":          m.mana_cost or "",
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
    source_path = RENDER_DIR / source_job_id / "deck.json"
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
    pip_dir = RENDER_DIR / job_id / "pips"

    # Reuse the source deck's pips (keeps the silhouette identical on re-renders).
    # The source set_symbol.png already carries the matching emblem, so callers
    # keep their copied symbol — return None here.
    if source_job_id:
        existing = mana_pips.load_mana_pips(RENDER_DIR / source_job_id / "pips")
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
        emblem.save(RENDER_DIR / job_id / "set_symbol.png", "PNG")
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


def _mark_job_error(job_id: str, e: Exception) -> None:
    """Common 'except' handling for the _run_* pipelines."""
    _jobs[job_id]["status"] = "error"
    _jobs[job_id]["error"]  = str(e)
    _push(job_id, "error", json.dumps({"msg": str(e)}))
    traceback.print_exc()   # full stack trace to server stdout/log


def _finalize_job(job_id: str) -> None:
    """Common 'finally' cleanup for the _run_* pipelines.

    Drops the (unserializable) cancel_event, caps the per-job SSE buffer so the
    ETA-ticker spam can't grow without bound, and trims the in-memory job store.
    """
    _jobs.get(job_id, {}).pop("cancel_event", None)
    msgs = _progress.get(job_id)
    if msgs and len(msgs) > 80:
        _progress[job_id] = msgs[-80:]
    _trim_in_memory_jobs()


# ── Background deck build ─────────────────────────────────────────────────────

def _run_build(job_id: str, req: BuildRequest):
    try:
        _jobs[job_id]["status"] = "building"

        ps_label    = PLAYSTYLES.get(req.playstyle, PLAYSTYLES["auto"])["label"]
        import_meta: dict = {}
        collection_stats: Optional[dict] = None  # C4: set in the generate branch when on

        if req.prebuilt_deck:
            # ── Phase-2 build: theme/render a decklist generated in phase 1 ───
            # (POST /api/deck/generate-list). Skip DeckBuilder entirely and use
            # the exact list the user reviewed when choosing tribe replacements.
            _push(job_id, "progress", json.dumps({"step": "commander", "msg": f"Looking up {req.commander_name}..."}))
            card = _scryfall.get_card_by_name(req.commander_name, fuzzy=True)
            if not card:
                raise ValueError(f"Commander not found: {req.commander_name}")
            deck = list(req.prebuilt_deck)
            stats = compute_stats(card, deck)
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
            # Partner/companion commanders aren't the face — render them as cards.
            for p in imported.partners:
                pc = dict(p); pc.setdefault("quantity", 1); deck.append(pc)
            stats = compute_stats(card, deck)
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

            profile        = build_commander_profile(card)
            active_themes  = resolve_themes(req.playstyle, profile.themes)
            slot_overrides = get_slot_adjustments(req.playstyle)

            owned = load_owned_names() if req.use_collection else set()
            if req.use_collection:
                _push(job_id, "progress", json.dumps({"step": "deck", "msg": (
                    f"Building from your collection ({len(owned)} owned cards)…"
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
            )
            # Collapse duplicate basics into quantity entries (theme/render once,
            # export replicates) — same model as imported decks.
            deck = aggregate_duplicates(deck)
            stats = compute_stats(card, deck)
            if req.use_collection:
                _spells = [card] + [c for c in deck
                                    if "basic" not in (c.get("type_line", "") or "").lower()]
                have = owned_count(_spells, owned)
                collection_stats = {
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
        _push(job_id, "progress", json.dumps({"step": "theme", "msg": "Freeing GPU for Ollama…"}))
        _wait_for_comfyui_unload(job_id)

        _llm = req.llm_model or None   # None → Themer uses default qwen3:14b
        _push(job_id, "progress", json.dumps({
            "step": "theme",
            "msg":  f"Theming cards with Ollama ({_llm or 'default'})..."
        }))

        # Fetched here (not just before art) so theming itself is cancellable —
        # a cancel during the LLM batches now stops the build instead of letting
        # all ~20 batches finish first.
        cancel_event = _jobs[job_id].get("cancel_event") or threading.Event()

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
                    "msg": f"[!] Ollama theming failed — falling back to plain card names. Error: {e}",
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
        sym_path = RENDER_DIR / job_id / "set_symbol.png"
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
        deck_json_path = RENDER_DIR / job_id / "deck.json"
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
            "imported":         bool(import_meta),
            "import_source":    import_meta.get("source", ""),
            "import_name":      import_meta.get("source_name", ""),
            "import_unresolved": import_meta.get("unresolved", []),
            "import_auto_face": import_meta.get("auto_face", False),
            "built_at":         time.time(),
        }
        deck_json_path.write_text(json.dumps(checkpoint), encoding="utf-8")

        # render_out is defined early so the inline-render callback can use it
        render_out = RENDER_DIR / job_id / "cards"
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
                _push(job_id, "progress", json.dumps({"step": "art", "msg": f"Evicting Ollama ({_evict_model}) from VRAM…"}))
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
        art_theme = req.art_theme or f"epic fantasy art centered on {name}"
        ro_mode   = req.art_style in ("ragnarok_online", "ragnarok_sprite")

        _push(job_id, "progress", json.dumps({"step": "commander", "msg": f"Custom card: {name}"}))

        # Art-style preset → themer medium/quality/vocabulary (same mapping as builds).
        from image_gen import get_all_presets as _gap
        _all_p = _gap()
        _style_meta = _all_p.get(req.art_style or "mtg_fantasy",
                                 _all_p.get("mtg_fantasy", next(iter(_all_p.values()))))

        _llm = req.llm_model or None
        cancel_event = _jobs[job_id].get("cancel_event") or threading.Event()

        # Does this run need the LLM? Only when AI writes the art prompt or themes it.
        custom_prompt = (req.art_prompt or "").strip()
        need_llm = (req.theme_mode == "full") or \
                   (req.theme_mode != "full" and req.art_prompt_mode != "custom") or \
                   (req.art_prompt_mode != "custom" and not custom_prompt)

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
                    "msg": f"⚠ Theming failed — using a basic art prompt. {e}", "warning": True}))

        if cancel_event.is_set():
            _jobs[job_id]["status"] = "cancelled"
            _push(job_id, "done", json.dumps({"job_id": job_id, "cancelled": True}))
            return

        # Custom art prompt (or fallback when theming was skipped/failed).
        if tc is None:
            prompt = custom_prompt or art_theme
            if ro_mode and prompt:
                from themer import apply_ro_tokens as _apply_ro
                prompt = _apply_ro(prompt, card, override_text=req.commander_prompt)
            tc = ThemedCard(name, name, prompt, card.get("flavor_text", ""), card)

        # Author mode: never let AI flavor clobber a flavor the user actually wrote.
        if req.theme_mode != "full" and card.get("flavor_text"):
            tc.flavor_text = card["flavor_text"]

        # ── Set symbol + pips + frame ─────────────────────────────────────────
        _push(job_id, "progress", json.dumps({"step": "symbol", "msg": "Generating set symbol…"}))
        sym = generate_set_symbol(art_theme, emblem_prompt=req.emblem_prompt or "")
        sym_path = RENDER_DIR / job_id / "set_symbol.png"
        sym_path.parent.mkdir(parents=True, exist_ok=True)
        sym.save(sym_path)

        if req.custom_pips and req.generate_art:
            _ensure_comfyui_ready(job_id)
        _pip_emblem = _setup_deck_pips(job_id, req.custom_pips, art_theme, req.emblem_prompt or "")
        card_renderer.set_frame_style(req.frame_style or "builtin")
        if _pip_emblem is not None:
            sym = _pip_emblem

        render_out = RENDER_DIR / job_id / "cards"
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
                "theme":           art_theme,
                "theme_spec":      req.theme_spec or {},
                "creativity":      req.creativity or "balanced",
                "theme_mode":      req.theme_mode,
                "art_prompt_mode": req.art_prompt_mode,
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
            (RENDER_DIR / job_id / "deck.json").write_text(json.dumps(payload), encoding="utf-8")
            _jobs[job_id].update(payload)
            return payload

        _persist("rendering", has_render=False)

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
                    gen = ImageGen(model_speed=req.model_speed, art_style=req.art_style,
                                   checkpoint=req.checkpoint,
                                   gen_settings=_resolve_gen_settings(req.gen_settings),
                                   frame_style=req.frame_style or "builtin")
                    if not gen.available:
                        _push(job_id, "progress", json.dumps({
                            "step": "art", "msg": "⚠ ComfyUI not available — rendering without generated art.",
                            "warning": True}))
                    else:
                        face_comfy_name: Optional[str] = None
                        if req.face_key and gen.face_method != "none":
                            _fp = get_face_paths(req.face_key)
                            if _fp:
                                face_comfy_name = gen.upload_face_to_comfy(_fp[0])
                                _push(job_id, "progress", json.dumps({
                                    "step": "art", "msg": f"Face loaded ({gen.face_method_label})"}))
                        _push(job_id, "progress", json.dumps({
                            "step": "art", "msg": f"[1/1] {tc.themed_name}",
                            "card_num": 1, "total": 1, "card_name": tc.themed_name,
                            "has_face": face_comfy_name is not None, "pct": 50}))
                        t0 = time.time()
                        try:
                            art_path = gen.generate(
                                tc.art_prompt,
                                str(Path("generated_art") / deck_slug / _safe_name(name)),
                                face_comfy_name=face_comfy_name,
                                face_gender=req.face_gender,
                                card_type=card.get("type_line", ""),
                            )
                        except Exception as _ge:
                            print(f"  [card] art gen raised: {_ge}")
                            traceback.print_exc()
                        _push(job_id, "progress", json.dumps({
                            "step": "art", "msg": f"[1/1] {tc.themed_name} — {'OK' if art_path else 'FAIL'}",
                            "card_num": 1, "total": 1, "pct": 100,
                            "last_ok": art_path is not None, "elapsed": round(time.time() - t0)}))
                _wait_for_comfyui_unload(job_id)

        if cancel_event.is_set():
            _persist("cancelled", has_render=False)
            _push(job_id, "done", json.dumps({"job_id": job_id, "cancelled": True}))
            return

        # ── Render the proxy ──────────────────────────────────────────────────
        _push(job_id, "progress", json.dumps({"step": "render", "msg": "Rendering card…"}))
        processed_oracle = _replace_card_self_ref(card.get("oracle_text", ""), name, tc.themed_name)
        art_img = _PIL.open(art_path) if (art_path and art_path.exists()) else None
        card_img = render_card(
            tc.card, tc.themed_name, processed_oracle,
            art_image=art_img, set_symbol=sym,
            flavor_text=tc.flavor_text or "",
            border_theme=req.border_theme or "",
        )
        card_img.save(render_out / f"{render_key}.png", "PNG")
        _push(job_id, "card_ready", json.dumps({"key": render_key, "name": tc.themed_name}))

        _persist("done", has_render=True)
        _push(job_id, "done", json.dumps({"job_id": job_id}))

    except Exception as e:
        _mark_job_error(job_id, e)
    finally:
        _finalize_job(job_id)


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
        deck_json_path = RENDER_DIR / job_id / "deck.json"
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
            "auto_theme_tribes": bool(source_data.get("auto_theme_tribes", True)),
            "custom_pips":      _rebuild_pips,
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
            from themer import OLLAMA_MODEL as _DEFAULT_OLLAMA
            from image_gen import _is_flux
            _evict_rt = source_data.get("llm_model") or _DEFAULT_OLLAMA

            # For non-FLUX models (SDXL, SD3.5), unload ComfyUI FIRST so the
            # subsequent Ollama-eviction VRAM gate can actually pass.  With FLUX
            # still resident in ComfyUI (~12 GB) the gate never reaches 16 GB and
            # wastes the full 120-second timeout before giving up.
            if req.checkpoint and not _is_flux(req.checkpoint):
                _push(job_id, "progress", json.dumps({"step": "art", "msg": "Unloading previous ComfyUI models for VRAM headroom…"}))
                _wait_for_comfyui_unload(job_id)

            _push(job_id, "progress", json.dumps({"step": "art", "msg": f"Evicting Ollama ({_evict_rt}) from VRAM…"}))
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
        # source_json_path is kept for the custom-prompt write-back near the end.
        source_json_path = RENDER_DIR / source_job_id / "deck.json"
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
        sym_path   = RENDER_DIR / source_job_id / "set_symbol.png"
        sym        = _PIL.open(sym_path) if sym_path.exists() else None

        # Reuse the source deck's custom pips so regenerated cards match the rest.
        _setup_deck_pips(source_job_id, bool(source_data.get("custom_pips", False)),
                         art_theme, source_data.get("emblem_prompt", ""))
        card_renderer.set_frame_style(source_data.get("frame_style", "builtin"))

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
        # Auto-start ComfyUI if down (regen needs it — wait for it to load).
        _ensure_comfyui_ready(job_id)
        health = ImageGen.health_check()
        if not health["ok"]:
            raise ValueError(f"ComfyUI not available: {health['message']}")

        # Evict Ollama from VRAM and confirm before loading models.
        from themer import OLLAMA_MODEL as _DEFAULT_OLLAMA
        from image_gen import _is_flux
        _evict_rg = source_data.get("llm_model") or _DEFAULT_OLLAMA

        # For non-FLUX models (SDXL, SD3.5), unload ComfyUI FIRST so the
        # subsequent Ollama-eviction VRAM gate can actually pass.  With FLUX
        # still resident in ComfyUI (~12 GB) the gate never reaches 16 GB and
        # wastes the full 120-second timeout before giving up.
        if req.checkpoint and not _is_flux(req.checkpoint):
            _push(job_id, "progress", json.dumps({"step": "art", "msg": "Unloading previous ComfyUI models for VRAM headroom…"}))
            _wait_for_comfyui_unload(job_id)

        _push(job_id, "progress", json.dumps({"step": "art", "msg": f"Evicting Ollama ({_evict_rg}) from VRAM…"}))
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

            from face_ref import is_human_card as _is_human_card

            for i, (tc, render_key, art_safe, has_custom) in enumerate(to_regen, 1):
                if cancel_event.is_set():
                    break

                # Face conditioning. Priority:
                #   1. Forced face → every selected card, any type (user's explicit pick).
                #   2. Commander face → the commander card.
                #   3. Crew faces → humanoid creature cards (round-robin).
                is_commander = tc.original_name == commander_original_name
                face_for_card   = None
                gender_for_card = "either"
                if force_face_comfy_name:
                    face_for_card   = force_face_comfy_name
                    gender_for_card = req.force_face_gender or "either"
                elif is_commander and face_comfy_name_for_cmd:
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
                    str(_Path("generated_art") / deck_slug / art_safe),
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
                                _cur_art_dir = RENDER_DIR / source_job_id / "art"
                                _cur_art_dir.mkdir(parents=True, exist_ok=True)
                                _shutil.copyfile(art_path, _cur_art_dir / f"{render_key}.png")
                        except OSError as _ce:
                            print(f"  [regen] could not stash current art for {render_key}: {_ce}")
                        # The new still invalidates any prior animation (it was made
                        # from the OLD art). Delete the stale clip so the tile shows
                        # the fresh still until the user re-animates.
                        _video_was_cleared = False
                        for _ext in ("mp4", "webp", "gif"):
                            _vp = RENDER_DIR / source_job_id / "videos" / f"{render_key}.{_ext}"
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
    import card_video
    from PIL import Image as _PIL
    from pathlib import Path as _Path

    def _safe(n: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in n)[:48]

    _deck_lock = _get_deck_regen_lock(source_job_id)
    _deck_lock.acquire()
    try:
        _jobs[job_id]["status"] = "building"
        source_json_path = RENDER_DIR / source_job_id / "deck.json"
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
        sym_path  = RENDER_DIR / source_job_id / "set_symbol.png"
        sym       = _PIL.open(sym_path) if sym_path.exists() else None
        _setup_deck_pips(source_job_id, bool(source_data.get("custom_pips", False)),
                         art_theme, source_data.get("emblem_prompt", ""))
        card_renderer.set_frame_style(source_data.get("frame_style", "builtin"))
        deck_slug = source_data.get("deck_slug") or ""
        border    = source_data.get("border_theme", "")
        videos_out = RENDER_DIR / source_job_id / "videos"
        videos_out.mkdir(parents=True, exist_ok=True)
        anim_src = RENDER_DIR / source_job_id / "_anim_src"
        anim_src.mkdir(parents=True, exist_ok=True)
        # Per-deck store of CURRENT raw art crops, written by regen (keyed by
        # render_key). When a card was rebuilt this holds its newest crop; the
        # original build crop in generated_art/<deck_slug>/ is stale for it.
        cur_art_dir = RENDER_DIR / source_job_id / "art"

        def _current_art_src(render_key, art_safe, cd):
            """Raw art crop for the card's CURRENTLY displayed version, for the I2V
            motion model. Prefers a regen-stashed crop (keyed by render_key), then
            the original build crop, then a Scryfall download."""
            regen_crop = cur_art_dir / f"{render_key}.png"
            if regen_crop.exists():
                return regen_crop
            build_crop = _Path("generated_art") / deck_slug / f"{art_safe}.png"
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
            png = RENDER_DIR / source_job_id / "cards" / f"{render_key}.png"
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


def _download_art_to(url: str, dest: "Path") -> Optional["Path"]:
    """Download a Scryfall art image to dest (PNG). Returns dest or None."""
    if not url:
        return None
    try:
        import requests as _rq
        r = _rq.get(url, timeout=20)
        if r.status_code == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
            return dest
    except Exception as e:
        print(f"  [animate] art download failed ({url}): {e}")
    return None


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
        # keywords is reset to [] so the themer re-derives mechanics from scratch;
        # oracle_text may already be themed from a prior pass, which is harmless.
        def _stored_to_raw(d: dict) -> dict:
            return {**_stored_card_to_dict(d), "keywords": []}

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
                    "msg": f"[!] Ollama theming failed — falling back to plain card names. Error: {e}",
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

        # Fallback to plain card names if theming failed
        if themed_cmd is None or themed_deck is None:
            def _plain(c): return ThemedCard(c["original_name"], c["original_name"], "", "", c)
            themed_cmd  = _plain(raw_commander)
            themed_deck = [_plain(c) for c in raw_deck]

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
                adir = Path("generated_art") / source_deck_slug
                for tc in [themed_cmd] + themed_deck:
                    safe = "".join(ch if ch.isalnum() else "_" for ch in tc.original_name)[:48]
                    p = adir / f"{safe}.png"
                    if p.exists():
                        paths[tc.original_name] = p
            return paths

        art_paths: dict[str, Optional[Path]] = {}
        effective_slug = source_deck_slug   # what deck.json records (where art lives)

        if not source_data.get("generate_art", False):
            art_paths = {}   # source was text-only (Scryfall art) — keep it that way
        else:
            _ensure_comfyui_ready(job_id)
            _health = ImageGen.health_check()
            _src_ckpt = source_data.get("checkpoint") or None
            if not _health["ok"]:
                art_paths = _reuse_source_art()
                _push(job_id, "progress", json.dumps({
                    "step": "art", "warning": True,
                    "msg": f"⚠ ComfyUI unavailable ({_health['message']}) — reused {sum(1 for v in art_paths.values() if v)} existing art image(s). Start ComfyUI and retheme again for fresh art.",
                }))
            else:
                from themer import OLLAMA_MODEL as _DEF_OLLAMA
                from image_gen import _is_flux as _isflux
                _ev = llm_model_rt or _DEF_OLLAMA
                if _src_ckpt and not _isflux(_src_ckpt):
                    _push(job_id, "progress", json.dumps({"step": "art", "msg": "Unloading previous ComfyUI models for VRAM headroom…"}))
                    _wait_for_comfyui_unload(job_id)
                _push(job_id, "progress", json.dumps({"step": "art", "msg": f"Evicting Ollama ({_ev}) from VRAM…"}))
                _wait_for_ollama_evict(_ev, job_id)
                # cancel_event already bound at the top of _run_retheme.
                _push(job_id, "progress", json.dumps({"step": "art", "msg": "Waiting for GPU…"}))
                with _art_lock:
                    try:
                        gen = ImageGen(model_speed=model_speed, art_style=art_style,
                                       checkpoint=_src_ckpt,
                                       gen_settings=_resolve_gen_settings_reusing(None, source_data),
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
        deck_json_path = RENDER_DIR / job_id / "deck.json"
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
            # Preserve the source deck's advanced gen settings (incl. style_variant)
            # so the rethemed deck keeps the same flavor on future regens.
            "gen_settings":     source_data.get("gen_settings", {}),
            "generate_art":     source_data.get("generate_art", False),
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


# ── Memory hygiene ────────────────────────────────────────────────────────────
_MAX_INMEM_JOBS = 6   # keep last N full job payloads in RAM; older fall to disk

def _trim_in_memory_jobs():
    """Evict old completed jobs' card payloads from memory. Status stays so
    /events and /status still work without re-reading disk."""
    done = [(jid, j) for jid, j in _jobs.items() if j.get("status") in ("done", "error")]
    if len(done) <= _MAX_INMEM_JOBS:
        return
    # Sort by built_at if present, else by insertion order
    done.sort(key=lambda kv: kv[1].get("built_at") or 0)
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

class ImportPreviewRequest(BaseModel):
    source:        str  = Field("", max_length=20000)  # URL or pasted decklist text
    force_refresh: bool = False                          # bypass the on-disk cache


def _safe_analyze(commander, deck):
    """Run the bracket analysis but never let it break the import preview."""
    try:
        import deck_analysis
        return deck_analysis.analyze_deck(commander, deck)
    except Exception as e:
        print(f"  [import-preview] deck analysis failed: {e}")
        return None


# --- MythGauntlet strength API (Myth Suite contract C3) ---------------------------------
# Simulation-grounded deck strength: MythGauntlet plays thousands of games and returns a
# measured Power Profile. Optional — if its local server (mythgauntlet serve) isn't up,
# import-preview silently falls back to the deck_analysis heuristic above.
MYTHGAUNTLET_URL = os.getenv("MYTHGAUNTLET_URL", "http://127.0.0.1:8020").rstrip("/")


def _deck_to_lines(commander, deck) -> str:
    """Render an imported deck as MythGauntlet's decklist text format."""
    lines = []
    if commander and commander.get("name"):
        lines += ["Commander:", f"1 {commander['name']}", ""]
    lines.append("Deck:")
    for c in deck:
        name = c.get("name", "")
        if name:
            lines.append(f"{c.get('quantity', 1)} {name}")
    return "\n".join(lines)


def _gauntlet_analyze(commander, deck):
    """Simulation-grounded strength from MythGauntlet; None if the service is unavailable."""
    try:
        resp = requests.post(
            f"{MYTHGAUNTLET_URL}/analyze",
            json={
                "deck": _deck_to_lines(commander, deck),
                "name": (commander or {}).get("name") or "deck",
                "runs": 300,
                "resilience": True,
                "combos": True,  # graded combo gate: real wincons vs durdles (Spellbook, cached)
            },
            timeout=25,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "engine_version": data.get("engine_version"),
            "power_profile": data.get("power_profile"),
            "combos": data.get("combos"),  # graded in-deck combos for the strength panel
            "unresolved": (data.get("deck") or {}).get("unresolved", []),
        }
    except Exception as e:
        print(f"  [import-preview] MythGauntlet strength API unavailable: {e}")
        return None


def _gauntlet_advise(commander, deck, axis=None):
    """Owned-card upgrade suggestions from MythGauntlet's ablation advisor.

    Returns the advise JSON, {"error": detail} for a meaningful 400 (no collection
    exported / bad axis), or None when the service is unreachable.
    """
    try:
        payload = {
            "deck": _deck_to_lines(commander, deck),
            "name": (commander or {}).get("name") or "deck",
            "runs": 300,
            "max_eval": 8,
        }
        if axis:
            payload["axis"] = axis
        resp = requests.post(f"{MYTHGAUNTLET_URL}/advise", json=payload, timeout=90)
        if resp.status_code == 400:
            try:
                return {"error": resp.json().get("detail", "advise failed")}
            except Exception:
                return {"error": "advise failed"}
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"  [advise] MythGauntlet strength API unavailable: {e}")
        return None


class AdviseDeckRequest(BaseModel):
    axis: Optional[str] = None  # None -> the deck's weakest axis


@app.post("/api/deck/{job_id}/advise")
def advise_deck(job_id: str, req: AdviseDeckRequest):
    """Upgrade suggestions from the user's collection for a FINISHED deck (suite C4).

    Every suggestion is a measured axis delta from MythGauntlet's ablation re-simulation,
    never popularity. Needs the strength API (:8020) and a Myth Suite collection export.
    """
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
    result = _gauntlet_advise(commander, deck, axis=req.axis)
    if result is None:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ── Collection manager (edit the canonical MythSuite/collection.csv) ──────────────
# The collection is the Myth Suite handoff file (contract C1): MythScanner writes it,
# Myth Forge + MythGauntlet read it for owned-aware building & advice. These endpoints
# let the user browse/add/edit/remove owned cards from inside Myth Forge; every write
# goes to the SAME canonical CSV (with a .bak) so the whole suite stays in sync.

def _collection_summary(rows: list[dict]) -> dict:
    return {
        "distinct":    len(rows),
        "total_cards": sum(int(r.get("count", 0)) for r in rows),
        "path":        str(suite_collection_path()),
        "exists":      suite_collection_path().exists(),
    }


@app.get("/api/collection")
def get_collection(q: str = "", offset: int = 0, limit: int = 200):
    """Owned cards (quantity-aware), optionally filtered by `q` and paginated.
    limit<=0 returns all matches (still capped at 5000 for safety)."""
    rows = load_collection()
    ql = (q or "").strip().casefold()
    filtered = [r for r in rows if ql in r["name"].casefold()] if ql else rows
    lim = 5000 if limit is None or limit <= 0 else min(limit, 5000)
    page = filtered[max(offset, 0): max(offset, 0) + lim]
    return {"cards": page, "matched": len(filtered), **_collection_summary(rows)}


class CollectionAddRequest(BaseModel):
    name:     str
    count:    int = 1
    validate: bool = True   # resolve the canonical Scryfall name before storing


@app.post("/api/collection/add")
def collection_add(req: CollectionAddRequest):
    """Add copies of a card. When validate=True the name is resolved against Scryfall
    (fuzzy) so the stored spelling matches how decklists reference it; an unresolvable
    name is a 404 so the UI can warn instead of silently storing a typo."""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Card name is required.")
    display = name
    if req.validate:
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
    rows = coll_add_card(name, max(int(req.count), 1), display_name=display)
    return {"cards": rows[:200], "resolved_name": display, **_collection_summary(rows)}


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
    name:  str
    count: int


@app.patch("/api/collection/count")
def collection_set_count(req: CollectionCountRequest):
    """Set a card's exact count (0 removes it)."""
    if not (req.name or "").strip():
        raise HTTPException(400, "Card name is required.")
    rows = coll_set_count(req.name.strip(), int(req.count))
    return {"cards": rows[:200], **_collection_summary(rows)}


@app.delete("/api/collection/{name}")
def collection_remove(name: str):
    """Remove a card entirely (matched on front-face name, case-insensitive)."""
    rows = coll_remove_card(name)
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
        raise HTTPException(503, f"Could not scan the collection (Scryfall): {e}")
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
    sim = _gauntlet_analyze(commander, deck)
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
        p = RENDER_DIR / job_id / "deck.json"
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
        p = RENDER_DIR / job_id / "deck.json"
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


def _gauntlet_duel(commander, deck, opponent_text, name_a, name_b, games):
    """Head-to-head win rate from MythGauntlet's Tier-2 adversarial engine.

    Returns the duel JSON, {"error": detail} for a meaningful 400 (unparseable
    opponent list), or None when the service is unreachable.
    """
    try:
        payload = {
            "deck_a": _deck_to_lines(commander, deck),
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
        commander, deck, req.opponent, name_a, req.opponent_name, req.games
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
        raise HTTPException(500, f"Import failed: {e}")

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
        "analysis":     _safe_analyze(imp.commander, imp.deck),
        "simulation":   _gauntlet_analyze(imp.commander, imp.deck),
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
        raise HTTPException(500, f"Import failed: {e}")

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
    stats = compute_stats(card, deck)
    face_auto = bool(imp.auto_face) and card is imp.commander

    job_id = uuid.uuid4().hex[:16]
    (RENDER_DIR / job_id).mkdir(parents=True, exist_ok=True)
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
        "import_unresolved": imp.unresolved,
        "import_auto_face":  face_auto,
        "built_at":          time.time(),
    }
    (RENDER_DIR / job_id / "deck.json").write_text(json.dumps(payload), encoding="utf-8")
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
    for p in sorted(RENDER_DIR.glob("*/deck.json"),
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
                "card_count":       len(data.get("deck", [])) + 1,
                "built_at":         data.get("built_at"),
                "thumbnail":        thumb,
                "partial":          status in ("rendering", "cancelled"),
                "is_copy":          bool(data.get("is_copy")),
                "copied_from":      data.get("copied_from", ""),
                "measured_bracket": lm_pp.get("bracket_estimate"),
                "measured_label":   lm_pp.get("bracket_label", ""),
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
    playstyle:      str = "auto"
    bracket:        int = 3
    use_collection: bool = False   # prefer owned cards (Myth Suite C4)


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
    profile        = build_commander_profile(card)
    active_themes  = resolve_themes(req.playstyle, profile.themes)
    slot_overrides = get_slot_adjustments(req.playstyle)
    owned = load_owned_names() if req.use_collection else set()
    deck = DeckBuilder(_scryfall).build(
        profile, theme_override=active_themes, slot_overrides=slot_overrides,
        playstyle_label=ps_label, bracket=req.bracket, owned=owned)
    deck  = aggregate_duplicates(deck)
    stats = compute_stats(card, deck)
    collection_stats = None
    if req.use_collection:
        _spells = [card] + [c for c in deck
                            if "basic" not in (c.get("type_line", "") or "").lower()]
        collection_stats = {
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
        raise HTTPException(503, f"Preview failed (is the LLM gateway up?): {e}")

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


_STYLE_SAMPLE_DIR = RENDER_DIR / "style_samples"


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
    path = _STYLE_SAMPLE_DIR / job_id / f"sample_{idx}.png"
    if not re.fullmatch(r"[0-9a-f]{16}", job_id) or not path.exists():
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
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip, _RATE_LIMIT_BUILD_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_BUILD_REQUESTS} per {_RATE_LIMIT_WINDOW}s")
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
    background_tasks.add_task(_run_animate_cards, new_job_id, job_id, req)
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

    Also backfills has_render flags by scanning the cards/ directory so that
    partial/cancelled builds show whatever art was generated rather than
    falling back to Scryfall images for everything.
    """
    p = RENDER_DIR / job_id / "deck.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("status") == "rendering":
                # "rendering" means art-gen was in flight when the server was
                # killed — treat as done so the partial deck is loadable.
                data["status"] = "done"
                try:
                    p.write_text(json.dumps(data), encoding="utf-8")
                except Exception:
                    pass
            # "cancelled" is left as-is so the frontend can show the correct state.

            # Backfill has_render flags: deck.json is written BEFORE art gen
            # begins so all cards start with has_render=False.  After a cancel
            # or crash, the PNG files that were rendered inline DO exist on disk
            # but deck.json was never updated.  Fix this so the gallery shows
            # the generated art instead of Scryfall fallbacks.
            cards_dir = RENDER_DIR / job_id / "cards"
            if cards_dir.exists():
                rendered = {fp.stem for fp in cards_dir.glob("*.png")}
                if rendered:
                    cmd = data.get("commander")
                    if isinstance(cmd, dict):
                        rk = cmd.get("render_key", "")
                        if rk and not cmd.get("has_render"):
                            cmd["has_render"] = rk in rendered
                    for card in data.get("deck") or []:
                        rk = card.get("render_key", "")
                        if rk and not card.get("has_render"):
                            card["has_render"] = rk in rendered

            # Backfill has_video the same way (animations persist as mp4/webp/gif).
            videos_dir = RENDER_DIR / job_id / "videos"
            if videos_dir.exists():
                # render_key → format (mp4 wins if multiple somehow coexist)
                vids: dict[str, str] = {}
                for ext in ("gif", "webp", "mp4"):
                    for fp in videos_dir.glob(f"*.{ext}"):
                        vids[fp.stem] = ext
                if vids:
                    def _mark_video(card):
                        fmt = vids.get(card.get("render_key"))
                        if fmt:
                            card["has_video"] = True
                            meta = card.get("video_meta")
                            if not isinstance(meta, dict):
                                card["video_meta"] = {"format": fmt}
                            elif not meta.get("format"):
                                meta["format"] = fmt
                    cmd = data.get("commander")
                    if isinstance(cmd, dict):
                        _mark_video(cmd)
                    for card in data.get("deck") or []:
                        _mark_video(card)

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
    # No AI render (e.g. a saved-but-un-themed imported deck): fall back to the card's
    # ORIGINAL Scryfall art so recalled imports still display. Look the card up in
    # deck.json by render_key and redirect to its stored image URL.
    dj = RENDER_DIR / job_id / "deck.json"
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
    videos = RENDER_DIR / job_id / "videos"
    for ext, media in _VIDEO_MEDIA_TYPES.items():   # mp4 preferred, then webp, gif
        path = videos / f"{render_key}.{ext}"
        if path.exists():
            return FileResponse(path, media_type=media,
                                headers={"Cache-Control": "no-cache, must-revalidate"})
    raise HTTPException(404, "Card video not found")


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


@app.get("/api/deck/{job_id}/export/zip")
def export_zip(job_id: str):
    job = _load_job_for_export(job_id)
    render_dir = RENDER_DIR / job_id
    try:
        data = build_zip(job["commander"], job["deck"], render_dir)
    except Exception as e:
        raise HTTPException(500, f"ZIP export failed: {e}")
    safe = "".join(c if c.isalnum() else "_" for c in job["commander"]["original_name"])[:30]
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}_deck.zip"'},
    )


@app.get("/api/deck/{job_id}/export/videos")
def export_videos(job_id: str):
    """ZIP of the deck's looping MP4 animations (only animated cards)."""
    job = _load_job_for_export(job_id)
    render_dir = RENDER_DIR / job_id
    try:
        data = build_video_zip(job["commander"], job["deck"], render_dir)
    except Exception as e:
        raise HTTPException(500, f"Video export failed: {e}")
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
    job = _load_job_for_export(job_id)
    render_dir = RENDER_DIR / job_id
    try:
        data = build_pdf(job["commander"], job["deck"], render_dir)
    except Exception as e:
        raise HTTPException(500, f"PDF export failed: {e}")
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
            deck_path = RENDER_DIR / deck_job_id / "deck.json"
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
            candidate = Path("generated_art") / deck_slug / f"{safe}.png"
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
                tmp_dir = RENDER_DIR / deck_job_id
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
        output_dir = RENDER_DIR / deck_job_id
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
    # Verify the deck exists
    deck_exists = (
        job_id in _jobs
        or (RENDER_DIR / job_id / "deck.json").exists()
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
    stl_path = RENDER_DIR / job_id / "commander_3d.stl"
    if not stl_path.exists():
        raise HTTPException(status_code=404,
                            detail="STL not found — generate it first via /generate-3d")

    # Determine a nice download filename from the deck commander name
    deck_data = _jobs.get(job_id, {})
    if not deck_data:
        deck_path = RENDER_DIR / job_id / "deck.json"
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
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        index = STATIC_DIR / "index.html"
        return FileResponse(index)


# ── Startup helpers ──────────────────────────────────────────────────────────
def _check_service(name: str, url: str, timeout: float = 2.0) -> bool:
    """Check if a service is running and responding."""
    try:
        requests.get(url, timeout=timeout)
        return True
    except Exception:
        return False


def _start_ollama() -> None:
    """Attempt to start Ollama if it's installed but not running."""
    import subprocess
    import sys
    import platform

    if _check_service("Ollama", "http://127.0.0.1:11434/api/tags"):
        print("  [OK] Ollama already running")
        return

    print("  [..] Ollama not detected, attempting to start...")
    try:
        # Start Ollama with concurrency enabled so the themer's batches run in
        # parallel (keeps the GPU busy across the idle gaps between batches).
        # Only applies when WE start Ollama — if it's already running, raise
        # OLLAMA_NUM_PARALLEL in your environment and restart Ollama yourself.
        _ollama_env = {**os.environ}
        _ollama_env.setdefault("OLLAMA_FLASH_ATTENTION", "1")
        _ollama_env.setdefault("OLLAMA_KV_CACHE_TYPE", "q8_0")
        if int(_ollama_env.get("OLLAMA_NUM_PARALLEL", "1") or "1") < 3:
            _ollama_env["OLLAMA_NUM_PARALLEL"] = "3"
        if platform.system() == "Windows":
            # Try to start Ollama on Windows
            subprocess.Popen(
                "ollama serve",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_ollama_env,
            )
        else:
            # Mac/Linux
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_ollama_env,
            )

        # Wait up to 15 seconds for Ollama to start
        for attempt in range(15):
            time.sleep(1)
            if _check_service("Ollama", "http://127.0.0.1:11434/api/tags"):
                print("  [OK] Ollama started successfully")
                return

        print("  [!] Ollama startup timed out (may still be initializing)")
    except Exception as e:
        print(f"  [X] Could not start Ollama: {e}")
        print(f"      Download & install from: https://ollama.ai")


def _resolve_comfyui_cmd() -> Optional[tuple[list[str], Path]]:
    """Build the ComfyUI backend launch command with --normalvram.

    Drives main.py directly via the ComfyUI Desktop's own CUDA venv python, using
    the same paths the Desktop app uses (read from %APPDATA%/ComfyUI/config.json).
    Bypasses the Desktop .exe because the Electron app hardcodes --highvram and
    ignores extraArgs overrides — verified from the actual process command lines.

    Returns (cmd, cwd) or None if the install can't be located.
    """
    import os
    appdata  = os.environ.get("APPDATA", "")
    cfg_path = Path(appdata) / "ComfyUI" / "config.json"
    extra_cfg = Path(appdata) / "ComfyUI" / "extra_models_config.yaml"

    # basePath from the Desktop app's config (models/user data root).
    base_dir: Optional[Path] = None
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            if cfg.get("basePath"):
                base_dir = Path(cfg["basePath"])
        except Exception:
            pass

    # main.py lives inside the Desktop app's Electron resources bundle.
    # Candidate exe roots, most likely first.
    exe_roots = [
        Path("E:/Games/comfy/ComfyUI"),
    ]
    # Also try resolving via the Start-Menu shortcut if pywin32 is available.
    try:
        import win32com.client as _w32  # type: ignore
        lnk = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "ComfyUI.lnk"
        if lnk.exists():
            tgt = Path(_w32.Dispatch("WScript.Shell").CreateShortcut(str(lnk)).TargetPath)
            exe_roots.insert(0, tgt.parent)
    except Exception:
        pass

    main_py: Optional[Path] = None
    for root in exe_roots:
        candidate = root / "resources" / "ComfyUI" / "main.py"
        if candidate.exists():
            main_py = candidate
            break

    if not main_py:
        return None

    # The Desktop app's own CUDA venv python — confirmed torch+cu130, CUDA=True.
    # basePath/.venv is where the Desktop installs its GPU runtime.
    venv_py: Optional[Path] = None
    if base_dir:
        for p in (base_dir / ".venv" / "Scripts" / "python.exe",
                  base_dir / ".venv" / "bin"     / "python"):
            if p.exists():
                venv_py = p
                break

    if venv_py is None:
        return None   # Can't find GPU python — don't risk CPU torch

    cmd = [
        str(venv_py), str(main_py),
        "--base-directory",   str(base_dir),
        "--user-directory",   str(base_dir / "user"),
        "--input-directory",  str(base_dir / "input"),
        "--output-directory", str(base_dir / "output"),
        "--listen",  "127.0.0.1",
        "--port",    "8188",
        "--log-stdout",
        # No --highvram: the Desktop .exe hardcodes it, which overflows 24 GB
        # (FLUX + LoRAs + ReActor) and spills ~5 GB to system RAM → slow. Driving
        # main.py directly lets us use the default NORMAL_VRAM instead (confirmed
        # "Set vram state to: NORMAL_VRAM" in the log; ~5.7 GB VRAM free at peak).
        #
        # --disable-async-offload: NORMAL_VRAM's async weight-offload path is buggy
        # in this ComfyUI build — it crashes CLIPTextEncode with
        # "'VRAMBuffer' object has no attribute 'get'" (comfy/ops.py get_cast_buffer).
        # --highvram dodged it only by never offloading. Disabling async offload
        # keeps NORMAL_VRAM working; generation verified end-to-end on cuda:0.
        "--disable-async-offload",
    ]
    if extra_cfg.exists():
        cmd += ["--extra-model-paths-config", str(extra_cfg)]
    return cmd, base_dir


# ── ComfyUI offload-fix guard ─────────────────────────────────────────────────
# This ComfyUI build crashes CLIPTextEncode in NORMAL_VRAM's async weight-offload
# path with "'VRAMBuffer' object has no attribute 'get'", which fails EVERY card
# (0/N art saved, silent Scryfall fallback — looks like "theming worked but no
# images"). _resolve_comfyui_cmd() launches with --disable-async-offload to avoid
# it, but a ComfyUI started another way (the Desktop .exe, a manual run, a stale
# duplicate) won't have the flag. These helpers detect that broken state at the
# art preflight and relaunch ComfyUI correctly.
def _list_comfyui_processes() -> "list[tuple[int, str]]":
    """Return (pid, command_line) for running ComfyUI backend processes.

    Windows-only (this rig); returns [] on other platforms or if inspection
    fails — callers treat [] as "can't tell, don't touch"."""
    import sys, subprocess
    if sys.platform != "win32":
        return []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*ComfyUI*main.py*' } | "
        "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return []
    procs: list[tuple[int, str]] = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if "\t" not in line:
            continue
        pid_s, cmd = line.split("\t", 1)
        try:
            procs.append((int(pid_s), cmd))
        except ValueError:
            pass
    return procs


def _comfyui_running_without_offload_fix() -> bool:
    """True iff a ComfyUI backend is running but at least one instance lacks
    --disable-async-offload (the unsafe state). Conservative: if we can't inspect
    the process list we return False so we never kill blindly."""
    procs = _list_comfyui_processes()
    if not procs:
        return False
    return any("disable-async-offload" not in cmd for _pid, cmd in procs)


def _kill_comfyui_processes() -> None:
    """Hard-kill every ComfyUI backend process (clears flagless + duplicate
    instances) so a clean one can be relaunched via _resolve_comfyui_cmd()."""
    import subprocess
    killed = 0
    for pid, _cmd in _list_comfyui_processes():
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, text=True, timeout=15)
            print(f"  [comfyui] killed flagless/duplicate ComfyUI backend PID {pid}", flush=True)
            killed += 1
        except Exception as e:
            print(f"  [comfyui] could not kill PID {pid}: {e}", flush=True)
    if killed:
        time.sleep(3)   # let the OS release :8188 and the VRAM before relaunch


def _ensure_comfyui_ready(job_id: str = "", *, wait_timeout: float = 300.0,
                          launch: bool = True) -> bool:
    """Ensure ComfyUI is running; auto-start it if it isn't.

    Returns True once ComfyUI responds.  If it's down and ``launch`` is True, the
    backend is started via the Desktop app's CUDA venv python with --normalvram,
    then we poll up to ``wait_timeout`` seconds.  A COLD start on this rig loads
    heavy 3D custom nodes (Hunyuan3D, TRELLIS2) + runs a DB migration and can take
    3-4 minutes; a warm start is ~20-30s.  The wait is generous so the first build
    of a session doesn't falsely fall back to Scryfall art while ComfyUI is still
    coming up.  Polls every 2s and returns the instant it responds.
    Progress is streamed over SSE when ``job_id`` is given.

    Serialized by _comfyui_start_lock so concurrent builds never spawn duplicates.
    """
    # Fast path: up AND launched with the offload fix → nothing to do.
    if _check_service("ComfyUI", "http://127.0.0.1:8188/system_stats") \
            and not _comfyui_running_without_offload_fix():
        return True
    if not launch:
        # Can't repair/launch — report whatever is currently up.
        return _check_service("ComfyUI", "http://127.0.0.1:8188/system_stats")

    def _emit(msg: str) -> None:
        if job_id:
            _push(job_id, "progress", json.dumps({"step": "art", "msg": msg}))
        print(f"  [comfyui] {msg}", flush=True)

    with _comfyui_start_lock:
        # Another thread may have started it (correctly) while we waited.
        _up = _check_service("ComfyUI", "http://127.0.0.1:8188/system_stats")
        if _up and not _comfyui_running_without_offload_fix():
            return True
        if _up:
            # ComfyUI is up but was launched WITHOUT --disable-async-offload (e.g.
            # the Desktop .exe or a manual/duplicate run). In that mode this build
            # crashes CLIPTextEncode on every card ('VRAMBuffer' bug) → 0 art saved.
            # Kill it and relaunch correctly.
            _emit("⚠ ComfyUI is running without --disable-async-offload — that mode "
                  "crashes image generation ('VRAMBuffer' bug, 0 cards rendered). "
                  "Restarting ComfyUI with the offload fix…")
            _kill_comfyui_processes()

        resolved = _resolve_comfyui_cmd()
        if resolved is None:
            _emit("⚠ ComfyUI backend not found — start ComfyUI Desktop manually then retry.")
            return False

        cmd, cwd = resolved
        import subprocess, sys
        # Capture ComfyUI's stdout/stderr to a logfile instead of DEVNULL so a
        # failed launch is diagnosable (was previously silent — "refuses to start"
        # with no clue why). Launch in its own process group so it survives a
        # Ctrl+C / restart of this server.
        log_path = RENDER_DIR / "comfyui_startup.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            _logf = open(log_path, "w", encoding="utf-8", errors="replace")
        except Exception:
            _logf = subprocess.DEVNULL
        _flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if sys.platform == "win32" else 0
        _emit("ComfyUI not running — starting backend (NORMAL_VRAM mode, first load ~60-90s)…")
        print(f"  [comfyui] launching: {cmd[0]} {cmd[1]} … (log: {log_path})", flush=True)
        try:
            subprocess.Popen(cmd, cwd=str(cwd),
                             stdout=_logf, stderr=subprocess.STDOUT,
                             creationflags=_flags)
        except Exception as e:
            _emit(f"⚠ Could not start ComfyUI backend: {e}")
            return False

        deadline = time.time() + wait_timeout
        while time.time() < deadline:
            time.sleep(2)
            if _check_service("ComfyUI", "http://127.0.0.1:8188/system_stats", timeout=1.5):
                _emit("✓ ComfyUI is ready.")
                return True

        _emit(f"⚠ ComfyUI did not become ready in {int(wait_timeout)}s — see {log_path} for the backend's output. Continuing without it.")
        return False


def _start_comfyui() -> None:
    """Start ComfyUI at server startup if it isn't already running.

    Thin wrapper over _ensure_comfyui_ready(); the heavy lifting (locating the
    install, launching, polling) lives there so builds can reuse it.
    """
    if _ensure_comfyui_ready():
        print("  [OK] ComfyUI ready", flush=True)


# ── Dev entry ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("Starting Myth Forge MTG Deck Builder...", flush=True)
    print(flush=True)

    # Boot Ollama + ComfyUI in a background daemon thread.  _start_comfyui()
    # launches ComfyUI and then polls for up to ~2 min for it to come up; running
    # it inline blocked uvicorn from binding port 8000 whenever ComfyUI wasn't
    # already running, so the whole app appeared to "fail to start".  The app
    # already tolerates these services being briefly offline (every build runs a
    # health check and falls back), so they can warm up in parallel.
    def _boot_services():
        try:
            _start_ollama()
            _start_comfyui()
        except Exception as _e:
            print(f"  [!] Background service startup error: {_e}", flush=True)

    print("Starting Ollama + ComfyUI in the background (server will not wait on them)...", flush=True)
    threading.Thread(target=_boot_services, name="service-boot", daemon=True).start()

    print(flush=True)
    print("Server endpoints:", flush=True)
    print("  API:      http://localhost:8000/api/", flush=True)
    print("  Frontend: http://localhost:8000/", flush=True)
    print(flush=True)
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
