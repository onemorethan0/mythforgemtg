# Documentation Index

Welcome to the MTG Commander Deck Builder documentation. This folder contains all guides and references.

---

## **Quick Start** (Start Here!)

👉 **First time?** Read: [`CHECKLIST_BEFORE_STARTING.txt`](../CHECKLIST_BEFORE_STARTING.txt) (in root)

Then come back here for more details.

---

## **For Users**

### Setup & Running
- **[STARTUP_INSTRUCTIONS.txt](STARTUP_INSTRUCTIONS.txt)** — Quick reference (5 min read)
- **[STARTUP_GUIDE.md](STARTUP_GUIDE.md)** — Complete setup with screenshots and troubleshooting (20 min read)

### Troubleshooting
- **[MAINTENANCE.md](MAINTENANCE.md)** — "Troubleshooting by Symptom" section
  - Card not displaying?
  - ComfyUI crashing?
  - Generation too slow?
  - Face conditioning not working?
  - Find your issue and fix it.

### Performance
- **[HARDWARE_OPTIMIZATION_GUIDE.md](HARDWARE_OPTIMIZATION_GUIDE.md)** — Make your GPU faster
  - Batch size tuning
  - VRAM optimization
  - RTX 3090 vs 4080 vs 4070 comparisons

---

## **For Developers**

⚠️ **Before making ANY code changes, read:**
- **[DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md)** — Mandatory best practices
  - Code change checklist
  - Documentation requirements
  - Testing procedures
  - Error handling standards
  - Self-check for each session

---

## **Project Setup Files** (in root)

| File | Purpose |
|------|---------|
| `paths_config.ps1` | Centralized configuration (edit this) |
| `START.bat` | Master startup script |
| `STOP.bat` | Master shutdown script |
| `launch_comfyui.ps1` | ComfyUI launcher |
| `README.md` | Main project documentation |
| `requirements.txt` | Python dependencies |

---

## **Directory Structure**

```
mtg_deck_builder/
├── README.md                          ← Start here (main docs)
├── CHECKLIST_BEFORE_STARTING.txt      ← One-page quick start
├── paths_config.ps1                   ← Edit this (configuration)
├── START.bat                          ← Double-click to start
├── STOP.bat                           ← Double-click to stop
│
├── server.py                          ← FastAPI backend
├── image_gen.py                       ← Image generation
├── themer.py                          ← Card theming
├── card_renderer.py                   ← Card rendering
├── ... (other source files)
│
└── docs/                              ← All documentation
    ├── INDEX.md                       ← You are here
    ├── STARTUP_INSTRUCTIONS.txt       ← Quick reference
    ├── STARTUP_GUIDE.md               ← Detailed setup
    ├── MAINTENANCE.md                 ← Troubleshooting
    ├── DEVELOPMENT_GUIDELINES.md      ← For developers
    ├── HARDWARE_OPTIMIZATION_GUIDE.md ← GPU tuning
    ├── STARTUP_REFINEMENT_SUMMARY.md  ← Technical details
    │
    └── archive/                       ← Old session notes (reference only)
        ├── BUG_FIXES_COMPLETE.md
        ├── DEPLOYMENT_READY.md
        ├── SESSION_COMPLETE.md
        └── ... (15 other historical files)
```

---

## **Common Tasks**

### "I want to start the app"
1. Edit `paths_config.ps1` (first time only)
2. Double-click `START.bat`
3. Open http://localhost:8000 in your browser

→ See: **[STARTUP_INSTRUCTIONS.txt](STARTUP_INSTRUCTIONS.txt)**

### "Something is broken"
1. Note the exact error message
2. Open **[MAINTENANCE.md](MAINTENANCE.md)**
3. Find "Troubleshooting by Symptom"
4. Locate your symptom and follow the fix

### "I want to modify the code"
1. Open **[DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md)**
2. Follow the "Code Change Checklist"
3. Update documentation at the same time
4. Test (Level 1-4) before committing

### "Generation is slow"
→ See: **[HARDWARE_OPTIMIZATION_GUIDE.md](HARDWARE_OPTIMIZATION_GUIDE.md)**
- Batch size tuning
- GPU VRAM optimization
- Checkpoint selection (FLUX vs SDXL)

### "Face conditioning isn't working"
→ See: **[MAINTENANCE.md](MAINTENANCE.md)** → "CUDA error: cublasLt64_12.dll missing"
- Install CUDA Toolkit 12.x
- Or generate without face photos as workaround

---

## **Archive** (Historical Reference)

The `archive/` folder contains documentation from previous development sessions. These are kept for reference but are outdated:
- `BUG_FIXES_COMPLETE.md`
- `DEPLOYMENT_READY.md`
- `SESSION_COMPLETE.md`
- ... and 13 others

**You don't need to read these.** The active documentation above is current.

---

## **Need Help?**

1. **Setup issue?** → [STARTUP_GUIDE.md](STARTUP_GUIDE.md)
2. **Troubleshooting?** → [MAINTENANCE.md](MAINTENANCE.md)
3. **Performance?** → [HARDWARE_OPTIMIZATION_GUIDE.md](HARDWARE_OPTIMIZATION_GUIDE.md)
4. **Development?** → [DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md)

---

## **Last Updated**

May 26, 2026 — Startup system refinement, bug fixes, documentation reorganization.
