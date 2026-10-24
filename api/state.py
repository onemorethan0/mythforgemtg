"""Shared server state: anchored paths, the in-memory job store, SSE progress, locks,
rate limiting, and loading a stored deck from disk.

Other modules import the containers (`_jobs`, `_progress`, ...) by name, but read
the paths as `state.RENDER_DIR` / `state.ART_DIR` / `state.STATIC_DIR`: those are
rebindable (tests point RENDER_DIR at a tmp dir), and one attribute read keeps
every module looking at the same value.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import traceback
from typing import AsyncGenerator, Optional

from fastapi import HTTPException, Request

from app_paths import app_path
from deck_builder import deck_quality_block
from scryfall_client import ScryfallClient

# Anchor to the script location, not the cwd — the server (and deck history)
# must work the same regardless of where it's launched from. See app_paths.py.
STATIC_DIR  = app_path("frontend", "dist")
RENDER_DIR  = app_path("renders")
ART_DIR     = app_path("generated_art")
RENDER_DIR.mkdir(exist_ok=True)

# Every job id this app mints is `uuid.uuid4().hex[:16]` — 16 lowercase hex chars —
# so validating that shape can never reject a real deck. 26 routes take {job_id}
# straight off the URL and interpolate it into a path under RENDER_DIR; a segment
# like `..%2f..%2f..` decodes AFTER routing (Starlette's `[^/]+` param regex only
# sees the encoded form), so it survives into the Path join. That reaches rmtree in
# DELETE /api/deck/{job_id} and FileResponse in the card-image/video/export routes.
# Not remotely exploitable today — the server binds 127.0.0.1 and CORS is an explicit
# localhost allowlist — but it is one config change away from mattering, and
# style_sample_image already validated while its 25 siblings did not.
_JOB_ID_RE = re.compile(r"[0-9a-f]{16}")


def _require_job_id(job_id: str) -> str:
    """Reject any job id that isn't the 16-hex-char shape we mint. Returns it."""
    if not _JOB_ID_RE.fullmatch(job_id):
        raise HTTPException(404, "Deck not found")
    return job_id

# In-memory job store (replace with Redis/SQLite for persistence)
_jobs: dict[str, dict] = {}
_progress: dict[str, list[str]] = {}   # job_id → list of SSE event strings
_JOB_TTL_SECONDS = 86400  # 24 hours — auto-expire old jobs to prevent memory accumulation

# Rate limiting for expensive endpoints (prevent resource exhaustion from floods)
_request_timestamps: dict[str, list[float]] = {}  # IP → list of request timestamps
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_BUILD_REQUESTS = 5  # max 5 builds per minute per IP
# Mentor chat/feedback/advise share `_check_rate_limit`'s mechanism but NOT its bucket
# or threshold: `_check_rate_limit` keys `_request_timestamps` by client_id ALONE, so
# passing the bare `client_ip` here (as the initial hardening pass did) put these three
# routes in the SAME bucket as every build/rebuild/regen route -- a real back-and-forth
# mentor conversation (one chat call + one feedback call per turn) exhausted a 5-per-60s
# budget sized for expensive GPU builds within a handful of turns. Found live 2026-08-25
# running an actual mentor campaign, not guessed. A distinct client-id suffix
# (`_CHAT_RATE_LIMIT_KEY`) gives these routes their own bucket, and a distinct threshold
# reflects that a chat turn is LLM-bound, not GPU-bound, so it can tolerate a much
# higher rate without risking the GPU contention the build limiter exists to prevent.
_RATE_LIMIT_CHAT_REQUESTS = 30  # max 30 mentor/advise calls per minute per IP
_CHAT_RATE_LIMIT_KEY = ":mentor"

# Global art-generation lock — ComfyUI is a single-GPU resource.
# Only one build may run art gen at a time; concurrent builds queue up here.
_art_lock = threading.Lock()

# Serializes ComfyUI auto-start so the startup thread and concurrent builds never
# spawn duplicate ComfyUI processes (each re-checks "is it up?" inside the lock).

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
    """Remove jobs older than _JOB_TTL_SECONDS to prevent memory leaks.

    Also sweeps the two other unbounded module-level dicts on the same hourly
    cadence: `_request_timestamps` (a rate-limit bucket per client IP — an IP
    that stops sending requests leaves an entry with an empty, but never-removed,
    timestamp list) and `_deck_regen_locks` (a per-source-deck lock — every deck
    that ever ran regen-cards left its lock behind forever, even long after the
    source job itself expired out of `_jobs`).
    """
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

    # Rate-limit buckets: drop timestamps outside the window, then drop any
    # client entry left with nothing in it.
    stale_clients = []
    for client_id, timestamps in _request_timestamps.items():
        fresh = [ts for ts in timestamps if (now - ts) < _RATE_LIMIT_WINDOW]
        if fresh:
            _request_timestamps[client_id] = fresh
        else:
            stale_clients.append(client_id)
    for client_id in stale_clients:
        _request_timestamps.pop(client_id, None)
    if stale_clients:
        print(f"  [cleanup] Dropped {len(stale_clients)} stale rate-limit bucket(s)")

    # Regen locks: a lock only needs to outlive its source deck's entry in _jobs.
    with _deck_regen_locks_meta_lock:
        orphaned_locks = [
            job_id for job_id in _deck_regen_locks
            if job_id not in _jobs
        ]
        for job_id in orphaned_locks:
            _deck_regen_locks.pop(job_id, None)
    if orphaned_locks:
        print(f"  [cleanup] Dropped {len(orphaned_locks)} orphaned deck-regen lock(s)")


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


# Keys on _jobs[job_id] that are internal-only and must NEVER appear in a
# JSON response — they're not serializable (threading primitives) or they're
# implementation detail the client has no business seeing.
_INTERNAL_JOB_KEYS = {"cancel_event"}

def _serializable_job(job: dict) -> dict:
    """Return a JSON-safe shallow copy of a job dict (strips threading.Event etc.)."""
    return {k: v for k, v in job.items() if k not in _INTERNAL_JOB_KEYS}


# The keys `deck_quality_block` produces. Adding one here is what makes an
# older stored block count as stale and get recomputed on load.
_QUALITY_KEYS = frozenset({"curve", "colors", "mana"})


def _backfill_quality(data: dict) -> None:
    """Derive stats.quality in place for a deck that predates it. No-op when present.

    Read-only on disk: the deck.json is NOT rewritten. Recomputing on load costs
    microseconds and avoids touching 158 stored files (and their mtimes, which History
    orders by) for a derived value.
    """
    stats = data.get("stats")
    if not isinstance(stats, dict):
        return
    quality = stats.get("quality")
    # A block written by an OLDER build is present but missing whatever keys have been
    # added since (`mana` landed after `curve`/`colors`), and a plain truthiness check
    # counts that as done — so a newly added panel silently never appears on the decks
    # built in between. Recompute unless every key the current block produces is there.
    if isinstance(quality, dict) and quality and _QUALITY_KEYS <= quality.keys():
        return
    try:
        stats["quality"] = deck_quality_block(data.get("commander") or {},
                                              data.get("deck") or [])
    except Exception:      # noqa: BLE001 — advisory; a bad stored deck must still load
        pass


def _load_deck_from_disk(job_id: str) -> Optional[dict]:
    """Load a completed deck from disk — used after server restarts.

    A deck.json written with status="rendering" means art-gen was in flight
    when the server was killed.  The deck data is valid; we just lack some
    rendered card images.  Normalise to "done" so the deck is loadable.

    Also backfills has_render flags by scanning the cards/ directory so that
    partial/cancelled builds show whatever art was generated rather than
    falling back to Scryfall images for everything.

    Backfills `stats.quality` the same way. It is computed at build time by
    compute_stats, so every deck built before that existed carries stats without it
    and StepDeck's Deck Health panel stays hidden — the feature would only ever appear
    on decks made after the upgrade. deck_quality is pure and offline, so deriving it
    on load is cheap and makes the whole existing library light up.
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
            # AFTER any write above: backfilling first let the derived value ride along
            # into that write, which contradicts this function's read-only promise.
            _backfill_quality(data)
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
