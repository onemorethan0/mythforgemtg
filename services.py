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




# ── VRAM gating ─────────────────────────────────────────────────────────────
# Moved out of server.py with the startup helpers: same concern (who is allowed to
# hold the GPU), and self-contained — the whole block needed nothing back from
# server.py once _VRAM_FLUX_REQUIRED_GB came with it.
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


