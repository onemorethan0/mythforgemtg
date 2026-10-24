"""
FastAPI app for Myth Forge -- `server:app` is the entry point (manage.bat, dev.bat, tests).

This file is the shell: lifespan startup checks, CORS, the stdout log tee behind
/api/logs, router wiring, the SPA mount, and the `python server.py` service boot.
Routes live in the api/ package (see api/__init__.py and docs/API.md):

  api/routes_strength.py    measure / advise / card-impact / mentor / breakdown / duel (engine :8020)
  api/routes_collection.py  /api/collection/*, card image + lookup
  api/routes_builds.py      build, cancel, rebuild, regen, animate, retheme, SSE events, status
  api/routes_decks.py       deck read / list / import / duplicate / delete, images, export, 3D
  api/routes_misc.py        health, model + style catalogues, frame config, face upload, logs

Background workers are api/jobs_*.py; shared job state and SSE are api/state.py.
"""
from __future__ import annotations

import asyncio
import logging
import sys as _sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Imported ahead of the log tee, as when every route lived in this file: image_gen and
# model3d swap sys.stdout for a UTF-8 wrapper on import (the tee must wrap it, not be
# replaced by it), and card_renderer prints its symbol-cache warm-up before the tee.
import image_gen  # noqa: F401
import card_renderer  # noqa: F401
import model3d  # noqa: F401
from api.logbuffer import _TeeStream

# ── In-memory log capture ──────────────────────────────────────────────────────
# Tee stdout/stderr into a bounded ring buffer (api/logbuffer.py) so the running
# server's output (startup checks, pipeline prints, tracebacks, uvicorn access logs)
# can be viewed from inside the app via /api/logs — regardless of how the process was
# launched (console, redirected file, or detached with no console at all).
# Wrapping happens before uvicorn.run() so uvicorn's log handlers bind to the tee and
# access logs are captured too.
_sys.stdout = _TeeStream(_sys.stdout)
_sys.stderr = _TeeStream(_sys.stderr)

# After the tee, so anything these print at import lands in the log buffer.
import api.routes_builds  # noqa: E402
import api.routes_collection  # noqa: E402
import api.routes_decks  # noqa: E402
import api.routes_misc  # noqa: E402
import api.routes_strength  # noqa: E402
from api import state  # noqa: E402
from api.state import _cleanup_expired_jobs, _push  # noqa: E402


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

# Route modules. First match wins, so a literal path has to stay ahead of a
# {param} sibling in another module: GET /api/deck/active (builds) before
# GET /api/deck/{job_id} (decks), GET /api/deck/advise/{id} (strength) before
# GET /api/deck/{job_id}/status (builds).
app.include_router(api.routes_strength.router)
app.include_router(api.routes_collection.router)
app.include_router(api.routes_builds.router)
app.include_router(api.routes_decks.router)
app.include_router(api.routes_misc.router)



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


# ── Serve React frontend ───────────────────────────────────────────────────────
if state.STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=state.STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        index = state.STATIC_DIR / "index.html"
        return FileResponse(index)


# Service lifecycle (ComfyUI + LLM backend) lives in services.py — see that module's
# docstring. Only the two boot helpers are needed here; the progress callback is
# registered below.
from services import (  # noqa: E402  (after app/_push are defined)
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
