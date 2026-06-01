# ComfyUI Setup & Configuration Notes

Operational reference for this machine's ComfyUI + Myth Forge stack.  
Captures every hard-won decision from debugging sessions so they don't need to be re-derived.

---

## System Configuration

| Component | Value |
|---|---|
| GPU | NVIDIA RTX 3090 — 24 GB VRAM |
| CUDA (system) | 13.2 (driver 596.36) |
| ComfyUI Desktop | v0.22.3 at `E:\Games\comfy\ComfyUI\ComfyUI.exe` |
| ComfyUI data/models | `C:\Users\rvn92\Documents\ComfyUI\` |
| ComfyUI CUDA venv | `C:\Users\rvn92\Documents\ComfyUI\.venv\` (torch 2.10.0+cu130) |
| Ollama | `qwen3:14b` default, ~9.9 GB VRAM when loaded |

---

## How ComfyUI Is Launched

### IMPORTANT: Do NOT use the Desktop `.exe` directly

`ComfyUI.exe` hardcodes `--highvram` in the command it passes to its backend Python process. The `extraArgs` field in `%APPDATA%\ComfyUI\config.json` is **ignored** for VRAM flags — confirmed from live process inspection.

With `--highvram` on a 24 GB card running FLUX dev fp8 + 3 LoRAs + ReActor:
- Total model footprint exceeds 24 GB
- Windows WDDM spills ~5–6 GB to shared system RAM over PCIe
- Each denoising step reads those weights at PCIe speed (~16 GB/s vs VRAM's ~900 GB/s)
- Result: 5–20× slowdown per generation step

### Correct launch command

Myth Forge's auto-launcher (`_ensure_comfyui_ready` in server.py) and manage.bat option 9 both use:

```
C:\Users\rvn92\Documents\ComfyUI\.venv\Scripts\python.exe
  E:\Games\comfy\ComfyUI\resources\ComfyUI\main.py
  --base-directory   C:\Users\rvn92\Documents\ComfyUI
  --user-directory   C:\Users\rvn92\Documents\ComfyUI\user
  --input-directory  C:\Users\rvn92\Documents\ComfyUI\input
  --output-directory C:\Users\rvn92\Documents\ComfyUI\output
  --listen 127.0.0.1 --port 8188
  --log-stdout
  --disable-async-offload
  --extra-model-paths-config %APPDATA%\ComfyUI\extra_models_config.yaml
```

Key flags:
- **No `--highvram`**: without any VRAM flag, ComfyUI auto-selects `NORMAL_VRAM` on the RTX 3090 — confirmed by the startup log `"Set vram state to: NORMAL_VRAM"`. NORMAL_VRAM keeps the FLUX UNet on-GPU for fast sampling but offloads the ~5 GB T5 text encoder after conditioning, keeping peak VRAM under the 24 GB limit.
- **`--disable-async-offload`**: NORMAL_VRAM mode enables async weight offloading, but this ComfyUI build has a bug in its async offload path (`'VRAMBuffer' object has no attribute 'get'` in `comfy/ops.py get_cast_buffer`) that crashes `CLIPTextEncode` on every generation. Disabling async offload keeps NORMAL_VRAM working correctly.

### Why the CUDA venv python specifically

`C:\Users\rvn92\Documents\ComfyUI\.venv` = **torch 2.10.0+cu130, CUDA available: True**

There is a second Python environment (`C:\Users\rvn92\ComfyUI\venv`) with **torch 2.12.0+cpu, CUDA available: False** — this produces the `[INFO] Device: cpu` message. Never launch using this env.

---

## VRAM Management

With NORMAL_VRAM, FLUX stays resident between generations (~16.6 GB used, ~7–8 GB free). The VRAM gate functions in server.py coordinate Ollama and ComfyUI to share the 24 GB without OOM.

### Thresholds

| Constant | Value | Meaning |
|---|---|---|
| `_VRAM_FLUX_REQUIRED_GB` | 16.0 | Minimum free VRAM before FLUX is allowed to load |
| `_VRAM_OLLAMA_CLEAR_GB` | 14.0 | Minimum free VRAM after ComfyUI `/free` before Ollama loads |

### VRAM metric: nvidia-smi (not ComfyUI internal)

`_comfyui_vram_free_gb()` calls `nvidia-smi --query-gpu=memory.free` — **system-wide across all processes**. The ComfyUI `/system_stats` `vram_free` field only reflects ComfyUI's own CUDA allocation pool and is blind to Ollama's ~10 GB. Using it caused every gate to read `25.77 GB free` even while Ollama held 10 GB.

### VRAM gate behavior by scenario

| Scenario | Free VRAM | Gate | Outcome |
|---|---|---|---|
| Ollama loaded (9.9 GB), FLUX needs to load | ~11 GB | 16 GB | ❌ Wait for Ollama to evict |
| After Ollama evicts | ~21 GB | 16 GB | ✅ FLUX loads |
| After FLUX gen, regen (Ollama not loaded) | ~8 GB | — | ✅ Returns immediately — FLUX is already resident |
| After `/free` on FLUX, Ollama about to load | ~21 GB | 14 GB | ✅ Ollama loads |

**Regen fast-path**: when `_wait_for_ollama_evict()` sees Ollama is not loaded and VRAM is low (FLUX is resident), it returns `True` immediately. This is the correct behavior — FLUX is already in place, ComfyUI is ready, no eviction needed.

### VRAM timeline for a full build

```
Startup:           ComfyUI idle — ~2 GB (baseline)     21 GB free
_wait_for_comfyui_unload():  POST /free → FLUX unloads → ~21 GB free ≥ 14 GB ✓
Ollama theming:    Ollama loads — ~10 GB               ~11 GB free
_wait_for_ollama_evict():  keep_alive=0 → Ollama evicts → ~21 GB free ≥ 16 GB ✓
FLUX generation:   FLUX+LoRAs+ReActor load — ~16.6 GB  ~7–8 GB free
After generation:  FLUX stays resident (NORMAL_VRAM)    ~7–8 GB free
```

---

## ReActor Face Conditioning

### Status: Working (CPU inference)

ReActor is installed and functional. Face detection (insightface buffalo_l) and face swapping (inswapper_128.onnx) run on **CPU**, not CUDA.

**Why CPU**: `onnxruntime-gpu` (any version) requires CUDA 12.x DLLs (`cublasLt64_12.dll`). The system has CUDA 13.2. When the CUDA provider DLL loads, it fails at initialization with `WinError 1114` — the CUDA 12.x interface is not binary-compatible with the 13.2 driver.

The `nvidia-cublas-cu12` Python package (already installed in the ComfyUI venv) provides the DLL, but attempting to load `onnxruntime_providers_cuda.dll` against it still fails at the driver interface level. This applies to onnxruntime versions 1.18.0, 1.26.0, and everything in between.

Installing cuDNN 9.x (`nvidia-cudnn-cu12>=9.0`) was tried — still fails.

### What was patched

Two files in the ReActor custom node were changed to force CPU-only:

**`custom_nodes/comfyui-reactor-node/scripts/reactor_swapper.py`** (line 32–40):
```python
# Original (tries CUDA first):
# if cuda is not None:
#     if cuda.is_available():
#         providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
#     else:
#         providers = ["CPUExecutionProvider"]
# else:
#     providers = ["CPUExecutionProvider"]

# Patched:
providers = ["CPUExecutionProvider"]  # CUDA 13.2 incompatible with onnxruntime CUDA 12.x DLLs
```

**`custom_nodes/comfyui-reactor-node/scripts/r_faceboost/restorer.py`** (same change).

These files are inside the ComfyUI custom node directory, not in the Myth Forge repo — they won't be overwritten by Myth Forge `git pull`. But a ComfyUI Manager **update of the ReActor node** will overwrite them. Re-apply the patch after any ReActor update.

### Performance impact

Insightface face detection: ~0.5–1s on CPU. Inswapper inference: ~1–2s per face on CPU. Negligible relative to FLUX's 25–40s per card.

---

## manage.bat Cheat Sheet

| Option | What it does |
|---|---|
| 1 | Start Myth Forge server (`python server.py`) |
| 2 | Kill any process on port 8000, then start fresh |
| 3 | Check status of ComfyUI (8188), Myth Forge (8000), Ollama (11434) |
| 4 | Stop the Myth Forge server |
| 5 | Kill all python.exe processes |
| 6 | First-time setup (pip install, npm install, npm build) |
| 7 | Download AI models (interactive) |
| 8 | Rebuild frontend only |
| **9** | **Start ComfyUI backend** with correct flags (no --highvram, --disable-async-offload) |

Option 9 does **not** hardcode any path — it calls the server's own resolver
(`python -c "import server; server._ensure_comfyui_ready(...)"`), which is the
single source of truth for locating the Desktop install + its CUDA venv (it reads
`%APPDATA%\ComfyUI\config.json`) and launches with the correct flags. If ComfyUI
moves, nothing here needs editing — only `server._resolve_comfyui_cmd()`.

---

## Myth Forge Auto-Start

When `python server.py` starts, Ollama and ComfyUI boot in a **background daemon thread** so uvicorn binds port 8000 immediately. The app gracefully handles both services being briefly offline.

`_ensure_comfyui_ready()` (server.py) is called before every build, rebuild, and regen. If ComfyUI is down it:
1. Locates `E:\Games\comfy\ComfyUI\resources\ComfyUI\main.py`
2. Launches via `.venv\Scripts\python.exe` with `--disable-async-offload` (no --highvram)
3. Polls `/system_stats` every 2s up to 150s
4. Streams "Starting ComfyUI…" progress to the build's SSE stream

---

## Troubleshooting

### `[vram] Waiting… X GB free (need 16+ for pre-FLUX VRAM gate)` loops forever

Ollama is loaded and must evict. Wait for theming to finish and `_wait_for_ollama_evict` to run. If stuck, check Ollama is responding: `curl http://127.0.0.1:11434/api/ps`.

### ComfyUI starts but generates on CPU

You launched via the Desktop `.exe` and it picked up the wrong Python (the `+cpu` env in `C:\Users\rvn92\ComfyUI\venv`). Kill it and use manage.bat option 9 or restart Myth Forge so it auto-starts correctly.

### `VRAMBuffer object has no attribute 'get'` in ComfyUI logs

ComfyUI was started without `--disable-async-offload`. Restart using the correct command (see above).

### ReActor fails after a ReActor node update

Re-apply the `CPUExecutionProvider` patch to both files listed above. The patch is trivial — just change the `providers` list.

### `5–10 GB shared GPU memory` in Task Manager

ComfyUI is running with `--highvram` (probably launched via Desktop `.exe`). Kill ComfyUI, restart via option 9 or Myth Forge auto-start.

### Generation takes 5–20× longer than expected (e.g., 10 min/card)

Same cause as above — VRAM overflow with `--highvram`. See shared GPU memory check.
