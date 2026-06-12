# Myth Forge - Scripts & Management

All server management is centralized in one menu system.

## Quick Start

### **Windows Users:**
```batch
manage.bat
```

### **Mac/Linux Users:**
```bash
bash start-mythforge.sh
```

---

## Management Menu (Windows)

Double-click `manage.bat` to open the interactive menu:

```
============================================
    MYTH FORGE - Server Management
============================================

Select an option:

  1. Start Development Server (recommended daily use)
  2. Clean Start (kill old processes, then start fresh)
  3. Check Server Status (ComfyUI, Ollama, Myth Forge)
  4. Stop Myth Forge Server
  5. Clean Up Orphaned Processes
  6. First-Time Setup (install dependencies)
  7. Download AI Models
  8. Rebuild Frontend
  9. Start ComfyUI (image generation backend, correct flags)

  0. Exit
```

> **Option 9 (Start ComfyUI)** launches ComfyUI with the correct flags (no `--highvram`, `--disable-async-offload`). Always use this (or let Myth Forge auto-start ComfyUI) rather than the Desktop `.exe` — see [COMFYUI_SETUP.md](./COMFYUI_SETUP.md).

---

## Menu Options Explained

### **1. Start Development Server** (Recommended)
- Starts Myth Forge server
- Assumes ComfyUI is already running
- Use this daily
- **Shortcut:** `python server.py`

### **2. Clean Start**
- Kills old Myth Forge processes on port 8000
- Waits 2 seconds for cleanup
- Starts fresh server
- Use when you get "port already in use" errors

### **3. Check Server Status**
- Shows status of all three services:
  - ComfyUI (port 8188)
  - Myth Forge (port 8000)
  - Ollama (port 11434)
- Shows running processes and PIDs
- No changes made, just informational

### **4. Stop Myth Forge Server**
- Gracefully stops the Myth Forge server
- Does not affect ComfyUI or Ollama
- Use before restarting

### **5. Clean Up Orphaned Processes**
- Kills all orphaned Python processes
- Use if you see `python.exe` in Task Manager with no window
- Safe: only targets background processes

### **6. First-Time Setup**
- Installs Python dependencies (`pip install -r requirements.txt`)
- Installs frontend dependencies (`npm install`)
- Builds frontend (`npm run build`)
- **Run once** when first setting up the project

### **7. Download AI Models**
- Interactive model downloader
- Choose which models to download:
  - FLUX Schnell (recommended, ~24GB)
  - FLUX Dev
  - Illustrious XL (for Ragnarok Online)
  - SD 3.5
- Saves to `ComfyUI/models/checkpoints/`

### **8. Rebuild Frontend**
- Runs `npm run build`
- Use after editing frontend code
- Remember to hard refresh browser (Ctrl+Shift+R)

---

## Naming Convention

All scripts follow consistent naming:

| Script | Purpose | When to Use |
|--------|---------|------------|
| `manage.bat` | Central menu system | Always - start here |
| `server.py` | Main application | Direct Python execution |
| `install.py` | Installer | First-time setup |
| `download-models.py` | Model downloader | Download checkpoints |
| `start-mythforge.sh` | Unix launcher | Mac/Linux users |

---

## Common Workflows

### Daily Use
```
1. Make sure ComfyUI is running in separate window
2. manage.bat → Option 1 (Start Development Server)
3. Open http://localhost:8000 in browser
```

### After Code Changes
```
1. manage.bat → Option 8 (Rebuild Frontend)
2. manage.bat → Option 1 (Start Development Server)
3. Browser: Hard refresh (Ctrl+Shift+R)
```

### Getting "Port Already In Use"
```
1. manage.bat → Option 2 (Clean Start)
   - Automatically kills old process and starts fresh
```

### Orphaned Processes in Task Manager
```
1. manage.bat → Option 3 (Check Status)
   - See what's running
2. manage.bat → Option 5 (Clean Up)
   - Kill orphaned processes
3. manage.bat → Option 1 (Start Fresh)
   - Restart normally
```

### First-Time Setup
```
1. manage.bat → Option 6 (First-Time Setup)
   - Install all dependencies
2. manage.bat → Option 7 (Download Models)
   - Download AI models
3. Start using the app normally
```

---

## Direct Command Access

If you prefer command line instead of menu:

### Start Server
```bash
python server.py
```

### Install Dependencies
```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build
```

### Download Models
```bash
python download-models.py
```

### Rebuild Frontend Only
```bash
cd frontend && npm run build
```

### Check What's Running
```bash
netstat -ano | find ":8000"   # Myth Forge
netstat -ano | find ":8188"   # ComfyUI
netstat -ano | find ":11434"  # Ollama
```

---

## Troubleshooting

### "Port Already In Use"
```
manage.bat → Option 2
```

### "Can't see python.exe in Task Manager"
```
manage.bat → Option 3
Shows all running processes
```

### Need to Kill Everything and Start Fresh
```
manage.bat → Option 5 (Clean Up)
Then restart everything manually
```

### Frontend Changes Not Showing
```
1. manage.bat → Option 8 (Rebuild)
2. Browser: Ctrl+Shift+R (hard refresh)
```

### Can't Connect to Server
```
1. manage.bat → Option 3 (Check Status)
2. Verify Myth Forge shows ✓ RUNNING
3. Check http://localhost:8000 in browser
```

---

## Mac/Linux Users

Use `start-mythforge.sh`:

```bash
bash start-mythforge.sh
```

This is equivalent to `manage.bat` option 1 (Start Development Server).

For other operations, use command line directly:
```bash
python download-models.py      # Download models
cd frontend && npm run build   # Rebuild frontend
python server.py              # Start server
```

---

## Utility scripts (`utilities/`)

### `generate_samples.py` — showcase sample cards

Re-renders showcase cards from any **already-built** deck (no GPU/LLM needed — pure PIL from stored data + existing art). For each deck it picks the commander + 3 creatures + 3 spells + 3 lands and writes full-res PNGs, a 10-up `contact_sheet.png`, and a `manifest.json`:

```bash
# one or more deck job ids (the folder names under renders/)
python utilities/generate_samples.py 532317b8f7ee4def

# or a JSON manifest mapping label -> job id (see sample_picks.json)
python utilities/generate_samples.py --manifest sample_picks.json --out renders/sample_cards
```

Custom pips, frame style, border theme, and rarity-tinted set symbols are all restored from the deck's `deck.json`, so samples match the app's own renders. Used to produce the README gallery (`docs/samples/`).

---

## Notes

- **ComfyUI must be running separately** - It's a standalone service
- **The LLM gateway auto-starts** when the server runs via `manage.bat` (llama-swap on :8010; or Ollama with `MYTHFORGE_LLM_BACKEND=ollama`)
- **These scripts only manage Myth Forge** on port 8000
- **Safe to run multiple times** - Menu won't break anything
- **Use the menu as your default** - It handles cleanup automatically

