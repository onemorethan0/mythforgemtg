# Installation

**Myth Forge** — a fully-local MTG Commander deck builder with AI-generated card art. Backend: **FastAPI** + **React/Vite**, with **Ollama** (theming) and **ComfyUI** (image gen).

For a feature overview see [README.md](./README.md); for model downloads see [MODELS.md](./MODELS.md); for the ComfyUI launch config see [COMFYUI_SETUP.md](./COMFYUI_SETUP.md).

## Prerequisites
- **Python 3.10+** (dev machine uses `C:\Python314\python.exe`) — check "Add to PATH" on Windows
- **Node.js 18+**
- **Ollama** (local LLM for theming) — https://ollama.ai
- **ComfyUI Desktop** (image generation) — https://www.comfy.org
- GPU recommended (NVIDIA 12–24 GB); without one, the app falls back to Scryfall art

## Install

**Windows:** `setup.bat`  **·**  **Mac/Linux:** `python install.py`

This installs Python deps, installs + builds the frontend, and creates working directories.

<details><summary>Manual steps</summary>

```bash
python -m pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
```
</details>

## Models
Download at least one checkpoint (FLUX Schnell recommended to start):

**Windows:** `download-models.bat`  **·**  **Mac/Linux:** `python download-models.py`

Full checkpoint/LoRA/face-model details: **[MODELS.md](./MODELS.md)**.

## Start
1. Start **ComfyUI** — use `manage.bat` → option 9, or let Myth Forge auto-start it. **Do NOT launch ComfyUI Desktop's `.exe` directly** — it forces `--highvram`, overflowing VRAM and causing 5–20× slowdowns ([COMFYUI_SETUP.md](./COMFYUI_SETUP.md)).
2. Start the server: `manage.bat` → option 1, or `dev.bat`, or `python server.py` (Mac/Linux: `bash start-mythforge.sh`). Ollama auto-starts.
3. Open **http://localhost:8000**.

## Ollama model
```bash
ollama pull qwen3:14b    # default; falls back to qwen3:32b → qwen2.5-coder:14b → gemma if missing
```

## Install troubleshooting
- **"Python/Node not found"** — install + add to PATH, then reopen the terminal.
- **Dependency install fails** — `npm cache clean --force`, then retry `npm install`.
- **Frontend changes don't show** — rebuild (`cd frontend && npm run build`) and hard-refresh (`Ctrl+Shift+R`). The server also auto-rebuilds on startup when `frontend/src` is newer than `frontend/dist`.
- **Port 8000 in use** — `manage.bat` → option 2 (Clean Start), or `netstat -ano | findstr :8000` then `taskkill /PID <id> /F`.
- **ComfyUI not detected / generating on CPU / very slow** — see [COMFYUI_SETUP.md](./COMFYUI_SETUP.md) (almost always the `--highvram` / wrong-venv issue).

Runtime troubleshooting by symptom: **[docs/MAINTENANCE.md](docs/MAINTENANCE.md)**.

---
*Myth Forge by OneMoreThan0 ⚔️*
