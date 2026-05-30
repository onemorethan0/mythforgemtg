# Documentation Index

Docs for **Myth Forge — MTG Commander Deck Builder**. The root [`README.md`](../README.md) is the main reference; this folder holds deeper guides. For an agent-oriented overview see [`CLAUDE.md`](../CLAUDE.md).

---

## Getting started
1. **First-time setup:** run `setup.bat` (Windows) or `python install.py` (Mac/Linux).
2. **Download models:** `manage.bat` → Download AI Models, or `python download-models.py`.
3. **Start:** `manage.bat` → Start Development Server (or `dev.bat`, or `python server.py`), then open http://localhost:8000.
4. ComfyUI (port 8188) must be running separately; Ollama (11434) auto-starts.

Full setup + troubleshooting: [`../INSTALL.md`](../INSTALL.md) · ComfyUI launch: [`../COMFYUI_SETUP.md`](../COMFYUI_SETUP.md)

> Note: `STARTUP_INSTRUCTIONS.txt` and the `archive/` notes describe a removed `START.bat`/`paths_config.ps1` startup system — ignore them; INSTALL.md is current.

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

## Archive
`archive/` holds outdated session notes from earlier development. They are historical only — **the docs above are current.** Safe to delete if you want to declutter.

_Last updated: May 2026 — synced with the actual `manage.bat`/`dev.bat` startup scripts; corrected references to a removed `START.bat`/`paths_config.ps1` system._
