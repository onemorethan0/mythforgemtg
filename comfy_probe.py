"""Find the port ComfyUI is listening on - one implementation for image_gen, model3d, card_video.

ComfyUI Desktop starts on 8000 and auto-increments when the port is taken; manual installs use
8188. A candidate counts only if its /system_stats JSON looks like ComfyUI's (Myth Forge itself
answers on 8000 with HTML).

Two copies of this probe used to exist (image_gen.py and model3d.py), both sequential and
uncached. With ComfyUI down each refused local connect costs ~2 s on Windows, so a status call
took 8-10 s, and /api/3d-health - an async route - froze the whole server for that long
(found 2026-10-25). Ports are now probed in parallel and the answer cached: a found port for
60 s, "not found" for only 10 s so a ComfyUI that comes up is noticed quickly. Code that
launches ComfyUI calls `reset()` so a build never acts on a stale "not running".
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

PORT_CANDIDATES = [8188, 8000, 8001, 8002]
DEFAULT_BASE = "http://127.0.0.1:8188"
FOUND_TTL = 60.0
MISSING_TTL = 10.0

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "url": None, "found": False}


def _probe(port: int) -> bool:
    try:
        r = requests.get(f"http://127.0.0.1:{port}/system_stats", timeout=2)
        if r.status_code == 200:
            data = r.json()
            return "system" in data or "devices" in data
    except (requests.RequestException, ValueError):
        pass   # refused, timed out, or answered but is not ComfyUI (e.g. our own server)
    return False


def detect_comfy_base() -> str:
    """The ComfyUI base URL, or DEFAULT_BASE when none answers (so callers report a clear error)."""
    now = time.monotonic()
    with _lock:
        ttl = FOUND_TTL if _cache["found"] else MISSING_TTL
        if _cache["url"] and now - _cache["at"] < ttl:
            return _cache["url"]
    with ThreadPoolExecutor(max_workers=len(PORT_CANDIDATES)) as pool:
        alive = list(pool.map(_probe, PORT_CANDIDATES))
    port = next((p for p, ok in zip(PORT_CANDIDATES, alive) if ok), None)
    url = f"http://127.0.0.1:{port}" if port else DEFAULT_BASE
    with _lock:
        _cache.update(at=time.monotonic(), url=url, found=port is not None)
    return url


def reset() -> None:
    """Forget the cached answer (call after starting or restarting ComfyUI)."""
    with _lock:
        _cache.update(at=0.0, url=None, found=False)
