"""Service lifecycle: starting, probing and repairing ComfyUI and the LLM backend.

Split out of server.py (2026-08-10), which had grown to 7,253 lines holding routing, job
orchestration, business logic AND this. These 11 functions are the cleanest seam in the
file: they were already physically contiguous, and the whole surface is three names
(`_start_llm_backend`, `_start_comfyui`, `_ensure_comfyui_ready`) plus a progress callback.

The one real coupling was `_push`, server.py's SSE progress buffer. Importing it back would
make a cycle, so it is INVERTED: server.py registers its emitter at import time via
`set_progress_emitter`, and this module defaults to a no-op. That also makes these functions
usable from a script or a test with no server at all.
"""

from __future__ import annotations

import glob
import json
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import requests

from app_paths import app_path

RENDER_DIR = app_path("renders")

# Serialises ComfyUI startup so concurrent builds never spawn duplicates. Lived in
# server.py but was only ever read here.
_comfyui_start_lock = threading.Lock()

_progress_emitter: Optional[Callable[[str, str, str], None]] = None


def set_progress_emitter(fn: Optional[Callable[[str, str, str], None]]) -> None:
    """Register the SSE push function (server._push). None restores the no-op."""
    global _progress_emitter
    _progress_emitter = fn


def _emit_progress(job_id: str, event: str, data: str) -> None:
    """Report progress if anyone is listening. A no-op off the server path."""
    if _progress_emitter is not None and job_id:
        _progress_emitter(job_id, event, data)


# ── Startup helpers ──────────────────────────────────────────────────────────
def _check_service(name: str, url: str, timeout: float = 2.0) -> bool:
    """Check if a service is running and responding."""
    try:
        requests.get(url, timeout=timeout)
        return True
    except Exception:
        return False


# The llama-swap launcher (the LLM gateway, shared with Odysseus). Override with
# MYTHFORGE_LLAMA_SWAP_LAUNCHER if the gateway lives elsewhere.
_LLAMA_SWAP_LAUNCHER = os.getenv(
    "MYTHFORGE_LLAMA_SWAP_LAUNCHER", r"E:\llama\start-llama-swap.bat"
)


def _start_llm_backend() -> None:
    """Start whichever LLM backend themer is actually configured to use.

    This dispatch is the whole point: the boot thread used to call _start_ollama()
    unconditionally, so on the default (llamacpp) backend `python server.py`
    tried to `ollama serve` a program that isn't installed any more, spent 15 s
    timing out, told the user to go download Ollama — and never started the
    gateway theming actually talks to. If :8010 wasn't already up (manage.bat is
    the only other thing that starts it), every build then failed at theming.
    """
    from themer import LLM_BACKEND
    if LLM_BACKEND == "llamacpp":
        _start_llama_swap()
    else:
        _start_ollama()


def _start_llama_swap() -> None:
    """Start the llama-swap gateway (:8010) if it isn't already listening.

    Mirrors manage.bat's :ensure_llama so both launch paths bring up the same
    service. llama-swap itself is cheap to start — it loads no GGUF until a
    request arrives — so this costs nothing at boot and holds no VRAM.
    """
    import subprocess
    import platform

    from themer import LLM_BASE

    if _check_service("llama-swap", f"{LLM_BASE}/v1/models"):
        print(f"  [OK] llama-swap gateway already running at {LLM_BASE}")
        return

    launcher = Path(_LLAMA_SWAP_LAUNCHER)
    if not launcher.exists():
        print(f"  [X] llama-swap launcher not found: {launcher}")
        print(f"      Theming needs the gateway at {LLM_BASE} — start it manually,")
        print(f"      or point MYTHFORGE_LLAMA_SWAP_LAUNCHER at the launcher.")
        return

    print(f"  [..] llama-swap not detected, starting {launcher.name}...")
    try:
        if platform.system() == "Windows":
            # Detached + no console: the gateway outlives this server (Odysseus
            # shares it) and doesn't steal focus with a window.
            flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            cmd = ["cmd", "/c", str(launcher)]
        else:
            flags = 0
            cmd = [str(launcher)]
        subprocess.Popen(
            cmd,
            cwd=str(launcher.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )

        for _attempt in range(30):
            time.sleep(1)
            if _check_service("llama-swap", f"{LLM_BASE}/v1/models"):
                print(f"  [OK] llama-swap started successfully on {LLM_BASE}")
                return

        print("  [!] llama-swap startup timed out (may still be initializing)")
    except Exception as e:
        print(f"  [X] Could not start llama-swap: {e}")
        print(f"      Start it manually: {launcher}")


def _start_ollama() -> None:
    """Attempt to start Ollama if it's installed but not running.

    Only reached on the legacy MYTHFORGE_LLM_BACKEND=ollama path — see
    _start_llm_backend().
    """
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
            _emit_progress(job_id, "progress", json.dumps({"step": "art", "msg": msg}))
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


