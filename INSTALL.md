# Installation

**Myth Forge** — a fully-local MTG Commander deck builder with AI-generated card art, plus the
**MythGauntlet engine** that measures deck strength by simulation. Backend: **FastAPI** +
**React/Vite**, a local **LLM** (theming), **ComfyUI** (image gen), and the engine on `:8020`.

For a feature overview see [README.md](./README.md); for model downloads see [MODELS.md](./MODELS.md); for the ComfyUI launch config see [COMFYUI_SETUP.md](./COMFYUI_SETUP.md).

## Prerequisites

**Required**
- **Python 3.12+** (dev machine uses `C:\Python314\python.exe`) — check "Add to PATH" on
  Windows. 3.12 is the floor because the bundled engine requires it.
- **Node.js 18+** — builds the React frontend.

**Optional — each unlocks one feature, and the app degrades honestly without it**
- **A local LLM** for theming (custom names, flavor, art prompts). Default backend is
  **llama.cpp via a llama-swap gateway** on `:8010`; **Ollama** on `:11434` still works if you
  prefer it (`MYTHFORGE_LLM_BACKEND=ollama`). Without either, decks keep their real card names.
- **ComfyUI Desktop** (https://www.comfy.org) for AI card art. Without it, cards render with
  real Scryfall art — the rest of the pipeline is unchanged.
- **GPU** (NVIDIA 12–24 GB) for art generation. Everything else runs on modest hardware.

Nothing extra is needed for the **engine** — it ships in `src/mythgauntlet/` and installs with
the Python deps below. See [Deck strength](#deck-strength-mythgauntlet-engine).

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
2. Start the server: `manage.bat` → option 1 (Mac/Linux: `bash start-mythforge.sh`).
   `manage.bat` also starts the **LLM gateway** (`:8010`) and the **strength engine** (`:8020`).
   `dev.bat` / `python server.py` start **only** the web server — use those when the gateway and
   engine are already up, or you'll get unthemed decks and "bracket unavailable".
3. Open **http://localhost:8000**.

## Theming model

Theming needs one chat model reachable over an OpenAI-compatible endpoint. Default is
**llama.cpp behind a llama-swap gateway** on `127.0.0.1:8010` — drop a GGUF in your models
folder, register it in `llama-swap.yaml` under the id `qwen3:14b`, and start the gateway.

Prefer Ollama? It still works:

```bash
ollama pull qwen3:14b                 # falls back to qwen3:32b -> qwen2.5-coder:14b -> gemma
set MYTHFORGE_LLM_BACKEND=ollama      # point Myth Forge at :11434 instead
```

Override the endpoint with `MYTHFORGE_LLM_BASE`. With no model reachable, theming is skipped
and cards keep their printed names — the build still completes.

## Deck strength (MythGauntlet engine)

The engine that measures brackets and deck strength lives at `src/mythgauntlet/` and runs as a
separate process on `:8020`. `manage.bat` starts it for you; it holds the card-semantics store
in memory, which is why it isn't folded into the web server.

First run needs card data:

```bash
set PYTHONPATH=src
python -m mythgauntlet fetch-data     # Scryfall bulk -> data/
python -m mythgauntlet doctor         # verify data / gateways / collection
```

⚠️ **The ~30k compiled card semantics are NOT included in this repo.** They are still being
trained and are withheld — see **[docs/ENGINE_DATA.md](docs/ENGINE_DATA.md)**. Without them the
engine falls back to Oracle-text heuristics: brackets and axes still compute, with lower
fidelity, and every report states its coverage. If you have a store of your own, point at it:

```bash
setx MYTHGAUNTLET_STORE "D:\my-ccm-store"   # a dir containing compiled/ and ledger.json
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
