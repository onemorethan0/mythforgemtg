# MTG Commander Deck Builder — Startup Guide

## Overview

The MTG deck builder requires **three services** to run:

| Service | Port | Status | Notes |
|---------|------|--------|-------|
| **Ollama** | 11434 | Required | LLM for card naming & theming |
| **ComfyUI** | 8188 | Required | AI image generation (FLUX/SDXL) |
| **FastAPI Server** | 8000 | Required | Backend API + React frontend |

All three are started automatically by the startup script. You don't need to start them manually.

---

## ⚡ Quick Start (3 Steps)

### Step 1: First-Time Configuration
Edit `paths_config.ps1` to match your system:

```powershell
# Find and update these 4 paths:
$global:PythonExe = "C:\Python314\python.exe"               # Your main Python interpreter
$global:ComfyPythonExe = "C:\Users\...\ComfyUI\.venv\Scripts\python.exe"
$global:ComfyMainPy = "E:\Games\comfy\ComfyUI\resources\ComfyUI\main.py"
$global:ComfyBaseDir = "C:\Users\...\Documents\ComfyUI"
```

**To validate your configuration:**
```powershell
# Open PowerShell in the mtg_deck_builder directory
. .\paths_config.ps1
Test-ConfigPaths
```

If all checks pass, you're ready to go!

### Step 2: Start All Services
**Simply double-click:**
```
START.bat
```

You'll see:
```
════════════════════════════════════════════════════════
  MTG Commander Deck Builder — Starting Services
════════════════════════════════════════════════════════

[1/3] Checking Ollama...
      ✓ Ollama ready

[2/3] Checking ComfyUI...
      ✓ ComfyUI ready

[3/3] Starting FastAPI server...
      ✓ FastAPI server ready

════════════════════════════════════════════════════════
  ✓ All services started successfully!
════════════════════════════════════════════════════════
```

The browser automatically opens to **http://localhost:8000**

### Step 3: Stop Services
**Simply double-click:**
```
STOP.bat
```

---

## 📋 What START.bat Does (In Detail)

```
START.bat
│
├─ Load paths from paths_config.ps1
│  └─ Validate all paths exist
│
├─ Check Ollama (port 11434)
│  ├─ If running: Skip to next step
│  └─ If stopped: Start it + wait up to 30s for readiness
│
├─ Check ComfyUI (port 8188)
│  ├─ If running: Skip to next step
│  └─ If stopped: Launch via launch_comfyui.ps1 + wait up to 90s
│
├─ Start FastAPI server (port 8000)
│  ├─ Kill any existing process on port 8000
│  ├─ Wait 2 seconds
│  └─ Start new server process + wait up to 30s
│
├─ Open browser to http://localhost:8000
│
└─ Return (services continue running in background)
```

---

## 🔧 Configuration File: `paths_config.ps1`

This file centralizes all path configuration so you only edit one place.

**Key Variables:**

```powershell
# Python executables
$global:PythonExe              # Main Python (for deck builder server)
$global:ComfyPythonExe         # ComfyUI's isolated Python venv

# ComfyUI
$global:ComfyMainPy            # Path to ComfyUI's main.py
$global:ComfyBaseDir           # Where ComfyUI stores models, input, output
$global:ComfyPort              # Port (default 8188)

# Deck Builder
$global:DeckBuilderDir         # Project root directory
$global:ServerPort             # API port (default 8000)
$global:ServerLogFile          # Where server.log is written

# Health check URLs (auto-built from above)
$global:OllamaHealthUrl        # Ollama readiness check
$global:ComfyHealthUrl         # ComfyUI readiness check
$global:ServerHealthUrl        # FastAPI readiness check
```

The `Test-ConfigPaths` function validates that all paths exist. If any are missing, it will tell you exactly which ones to fix.

---

## ❌ Troubleshooting

### Ollama Not Starting?

**Error:** `[ERROR] Ollama is not running!`

**Solution:**
1. Install Ollama: https://ollama.ai
2. Pull the model: `ollama pull qwen3:14b`
3. Test it: `ollama serve`
4. It should listen on `http://127.0.0.1:11434`

---

### ComfyUI Not Starting?

**Error:** `[✗ FAILED] ComfyUI did not respond after 90 seconds`

**Cause:** Paths in `paths_config.ps1` are wrong or ComfyUI is misconfigured.

**Solution:**
1. Open PowerShell and validate: `. .\paths_config.ps1; Test-ConfigPaths`
2. Manually test ComfyUI:
   ```cmd
   cd C:\Users\...\ComfyUI
   .\.venv\Scripts\python.exe E:\Games\comfy\ComfyUI\resources\ComfyUI\main.py --port 8188
   ```
3. Check that `http://localhost:8188/system_stats` responds
4. Check ComfyUI console for errors

---

### FastAPI Server Not Starting?

**Error:** `[✗ FAILED] FastAPI did not respond after 30 seconds`

**Check:**
1. Is Python installed? `python --version`
2. Check `server.log` for error messages
3. Are dependencies installed? `pip install -r requirements.txt`
4. Is port 8000 already in use?
   ```cmd
   netstat -ano | findstr :8000
   taskkill /PID <process_id> /F
   ```

---

### Port Already in Use?

**Error:** `[ERROR] Port 8000 is already in use`

**Solution 1: Change the port**
Edit `paths_config.ps1`:
```powershell
$global:ServerPort = 8001  # Use 8001 instead of 8000
```

**Solution 2: Kill the existing process**
```cmd
netstat -ano | findstr :8000
taskkill /PID <process_id> /F
```

---

## 📁 Project Structure

```
mtg_deck_builder/
├── START.bat                   ← Use this to start all services
├── STOP.bat                    ← Use this to stop all services
├── paths_config.ps1            ← Edit this with your paths
├── launch_comfyui.ps1          ← Used by START.bat (don't edit)
├── server.py                   ← FastAPI backend (do not run directly)
├── server.log                  ← Logs (auto-created)
├── requirements.txt            ← Python dependencies
├── STARTUP_GUIDE.md            ← This file
├── STARTUP_GUIDE.md            ← This file
│
├── utilities/                  ← Optional helper scripts
│   ├── download_new_loras.ps1
│   ├── move_downloaded_loras.ps1
│   └── complete_flux_dev_download.ps1
│
├── card_assets/                ← MTG frame graphics
├── frontend/                   ← React web interface
└── [other source files]        ← Python modules (themer, image_gen, etc.)
```

---

## 🖥️ Service Status

To check if services are running without starting the full app:

```powershell
# Ollama
Invoke-WebRequest http://127.0.0.1:11434/api/tags -UseBasicParsing

# ComfyUI
Invoke-WebRequest http://127.0.0.1:8188/system_stats -UseBasicParsing

# FastAPI
Invoke-WebRequest http://127.0.0.1:8000/api/playstyles -UseBasicParsing
```

All should return `StatusCode : 200`.

---

## 🚀 Advanced Usage

### Restarting After Code Changes

If you modify `server.py` or other Python files:
```cmd
STOP.bat
START.bat
```

The startup script automatically kills the old server and starts a fresh one.

### Running Services Manually (Advanced)

If you want to run services in separate terminal windows for debugging:

**Terminal 1 — Ollama:**
```cmd
ollama serve
```

**Terminal 2 — ComfyUI:**
```cmd
cd C:\Users\...\ComfyUI
.\.venv\Scripts\python.exe E:\Games\comfy\ComfyUI\resources\ComfyUI\main.py --port 8188 --listen 127.0.0.1
```

**Terminal 3 — FastAPI:**
```cmd
cd C:\Users\...\mtg_deck_builder
python server.py
```

Then open http://localhost:8000

### Viewing Live Logs

While the server is running, you can monitor logs:

```cmd
# PowerShell: Follow server logs in real-time
Get-Content -Path server.log -Tail 20 -Wait
```

---

## 📞 Getting Help

If something goes wrong:

1. **Check error messages** — START.bat and STOP.bat print clear error messages
2. **Check server.log** — `server.log` has detailed Python tracebacks
3. **Validate paths** — Run `Test-ConfigPaths` in PowerShell
4. **Check ports** — `netstat -ano | findstr :8000` etc.
5. **Restart Windows** — Sometimes the nuclear option is needed

---

## ✅ Checklist for First-Time Setup

- [ ] Installed Python 3.11+ (or later)
- [ ] Installed Ollama and pulled `qwen3:14b`
- [ ] Installed ComfyUI with FLUX checkpoint
- [ ] Edited `paths_config.ps1` with your paths
- [ ] Ran `Test-ConfigPaths` and all checks passed
- [ ] Double-clicked `START.bat` and it opened the browser
- [ ] Built a test deck to verify image generation works
- [ ] Tested `STOP.bat` to ensure services shut down cleanly

Once all these are done, you're set! The deck builder is ready to use.

---

## 🎯 Next Steps

1. Go to http://localhost:8000
2. Enter a commander name (e.g., "Omnath, Locus of All")
3. Pick a playstyle (e.g., "Landfall Ramp")
4. (Optional) Upload a face photo
5. Choose a theme (e.g., "enchanted forest")
6. Click "Build Deck"
7. Wait for generation (~70 minutes for FLUX Dev, ~20 for Schnell)
8. Download your deck or print to PDF

Enjoy! 🎴
