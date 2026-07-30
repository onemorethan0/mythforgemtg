# Documentation Index

Docs for **Myth Forge — MTG Commander Deck Builder**. The root [`README.md`](../README.md) is the main reference; this folder holds deeper guides. For an agent-oriented overview see [`CLAUDE.md`](../CLAUDE.md).

---

## Getting started
1. **First-time setup:** run `setup.bat` (Windows) or `python install.py` (Mac/Linux).
2. **Download models:** `manage.bat` → Download AI Models, or `python download-models.py`.
3. **Start:** `manage.bat` → Start Development Server (or `dev.bat`, or `python server.py`), then open http://localhost:8000.
4. ComfyUI (port 8188) and the local LLM gateway (8010) run separately — `manage.bat` starts
   the gateway and the strength engine for you.
5. **Verify:** `python verify-setup.py` checks Python deps, the frontend build, the engine, and
   whether the strength API is up.

Full setup + troubleshooting: [`../INSTALL.md`](../INSTALL.md) · ComfyUI launch: [`../COMFYUI_SETUP.md`](../COMFYUI_SETUP.md)

> Note: [`STARTUP_GUIDE.md`](STARTUP_GUIDE.md) is a superseded stub describing an old `START.bat`/`paths_config.ps1` system — ignore it; INSTALL.md is current.

## Deck strength engine (MythGauntlet)
The engine that measures brackets and deck strength ships in this repo at `src/mythgauntlet/`
(merged 2026-07-29 from its own repo, so there is one install and one analysis implementation).
- **What data is and isn't included:** [`ENGINE_DATA.md`](ENGINE_DATA.md) — the ~30k compiled
  card semantics are withheld while training completes; the engine degrades to Oracle-text
  heuristics without them. **Read this first if brackets look imprecise.**
- **Engine internals:** [`engine/`](engine/) — `ARCHITECTURE.md`, `SIMULATION.md` (what each
  tier models and every documented simplification), `CARD_SEMANTICS.md` (the CCM schema,
  validation gates and compiler), `LEARNING.md`, `DATA_SOURCES.md`, `SUITE_PLAN.md` (the
  collection contract shared with MythScanner), `STATUS.md` (measured state + what's next).

## For users
- **Troubleshooting by symptom:** [`MAINTENANCE.md`](MAINTENANCE.md)
- **GPU/performance tuning:** [`HARDWARE_OPTIMIZATION_GUIDE.md`](HARDWARE_OPTIMIZATION_GUIDE.md)

## For developers
- **Read before changing code:** [`DEVELOPMENT_GUIDELINES.md`](DEVELOPMENT_GUIDELINES.md)
- **Architecture & conventions:** [`../CLAUDE.md`](../CLAUDE.md)

## Real entry-point scripts (root)
| Script | Purpose |
|--------|---------|
| `setup.bat` / `install.py` | One-time install (deps + frontend build) |
| `manage.bat` | Menu: start/stop server, status, download models |
| `dev.bat` | Start the dev server directly |
| `download-models.py` | Download checkpoints/LoRAs/face models |
| `start-mythforge.sh` | Mac/Linux start helper |

---

_Last updated: June 2026 — synced with the actual `manage.bat`/`dev.bat` startup scripts; corrected references to a removed `START.bat`/`paths_config.ps1` system._
