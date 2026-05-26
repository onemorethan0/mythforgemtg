# Maintenance Guide — MTG Commander Deck Builder

## Overview

This guide covers routine maintenance, troubleshooting, and operational procedures for the MTG Commander Deck Builder. It's designed to help diagnose issues, optimize performance, and keep the system running smoothly.

---

## Table of Contents

1. [Regular Maintenance Tasks](#regular-maintenance-tasks)
2. [Troubleshooting by Symptom](#troubleshooting-by-symptom)
3. [Service Health Checks](#service-health-checks)
4. [Performance Optimization](#performance-optimization)
5. [Adding New Features](#adding-new-features)
6. [Version Updates and Dependencies](#version-updates-and-dependencies)

---

## Regular Maintenance Tasks

### Weekly
- [ ] Check disk space: `C:\Users\{user}\Documents\ComfyUI\output` directory (images accumulate over time)
- [ ] Review `server.log` for warnings: `findstr "WARNING\|ERROR" server.log`
- [ ] Verify ComfyUI VRAM usage doesn't exceed 90% during generation (use NVIDIA App or Task Manager)

### Monthly
- [ ] Clean up old generated images: Backup `output/` folder, then delete images older than 30 days
- [ ] Verify all startup services are still responsive: Run `START.bat` → check all three services start → run `STOP.bat`
- [ ] Check for ComfyUI updates: `pip list | findstr comfyui` → compare with https://github.com/comfyanonymous/ComfyUI/releases

### Before Major Changes
- [ ] **Backup deck database**: Copy `decks/` folder to external drive
- [ ] **Document current state**: Note which LoRAs, models, and art styles are active
- [ ] **Test basic functionality**: Generate 1 card successfully before making changes

---

## Troubleshooting by Symptom

### Symptom: "ComfyUI is not running" error but ComfyUI is actually running

**Root causes:**
1. ComfyUI is running on a different port (not 8188)
2. Windows firewall is blocking localhost connections
3. ComfyUI started but hasn't finished initializing

**Diagnosis:**
```powershell
# Check if ComfyUI is listening on port 8188
netstat -ano | findstr ":8188"

# If you see a line with "LISTENING", ComfyUI is running
# If not, ComfyUI crashed or never started

# Check ComfyUI logs (if running in terminal):
# The terminal window should show "Server started at http://127.0.0.1:8188"
```

**Fix:**
- **If ComfyUI crashed**: Check launch_comfyui.ps1 output for error messages; common issues are missing Python packages (run `pip install -r requirements-comfyui.txt`)
- **If firewall is blocking**: Add exception for localhost in Windows Defender Firewall
  - Settings → Firewall → Allow an app through firewall → Add Python.exe
- **If it hasn't initialized**: Wait 30-60 seconds for ComfyUI to load models; check system.log in ComfyUI directory

---

### Symptom: Images generate very slowly (211 seconds per image or more)

**Root causes:**
1. GPU VRAM is exhausted, system is using CPU fallback
2. GPU is power-limited (PSU insufficient or driver issue)
3. Disk is slow (NVMe vs. HDD makes a difference)

**Diagnosis:**
```powershell
# Check GPU memory during generation:
# Open NVIDIA App or Task Manager → Performance tab
# Watch GPU Memory during generation
# If it exceeds 20GB on a 24GB card, VRAM is exhausted

# Check if generation is using GPU or CPU:
# In server.log, look for performance timing:
INFO:     127.0.0.1:... - "POST /api/deck/.../regen-cards" - execution took 15.2s
# 15s is normal (GPU). 200s indicates CPU fallback

# Check disk speed:
# In ComfyUI output folder, check recent image file timestamps
# If saving takes >10 seconds per image, disk is bottleneck
```

**Fixes:**
1. **Free GPU memory**: Run `STOP.bat` to stop all services and fully release GPU
   - Sometimes ComfyUI holds onto VRAM even after generation
   - Restart ComfyUI: `STOP.bat` → wait 10s → `START.bat`

2. **Reduce batch size**: Edit `server.py` line ~200, reduce batch_size from 10 to 5
   ```python
   batch_size = 5  # Was 10, reduce if VRAM exhaustion
   ```

3. **Use lower-resolution checkpoint**: FLUX 1.0 is slower than SDXL
   - Use SDXL for quick iterations
   - Use FLUX only for final high-quality renders

4. **Upgrade PSU or GPU**: If consistently >200s per image, hardware may be insufficient
   - RTX 3090 should generate in 10-35s depending on style
   - RTX 4070 should generate in 15-40s

---

### Symptom: "Card not displaying after generation" or "Fallback card shown"

**Root causes:**
1. Generation completed but PNG file wasn't saved correctly
2. Frontend didn't receive SSE event indicating card was ready
3. Card filename doesn't match the key sent in card_ready event

**Diagnosis:**
```powershell
# Check if PNG files were created:
ls C:\Users\{user}\Documents\ComfyUI\output\*.png | Sort-Object LastWriteTime -Descending | Select -First 5

# Check server log for card_ready events:
findstr "card_ready" server.log

# If no card_ready events, generation didn't complete successfully
# If card_ready exists, check the key matches the filename:
# Example: card_ready event says "key": "Azusa_000"
#          file should be: Azusa_000.png (NOT Azusa.png or Azusa_0.png)
```

**Fixes:**
1. **Verify indexed render_keys are used**: 
   - Check server.py lines 834-869 (commander card rendering)
   - Ensure _render_keys_inline mapping is created BEFORE card generation
   - Verify PNG filenames use format: `{safe_name}_{index:03d}.png`

2. **Check frontend is receiving SSE events**:
   - Open browser DevTools (F12) → Network tab → filter for "events"
   - Start a generation
   - You should see a connection to `/api/deck/{deck_id}/events` with SSE stream
   - Watch for `card_ready` messages with `"key"` field

3. **Manual file check**:
   - Generate 1 card
   - Check `ComfyUI/output/` for PNG files
   - Verify filename exactly matches the card_ready event key

---

### Symptom: ComfyUI crashes immediately after image generation

**Root causes:**
1. GPU memory not properly released between generations (very rare with ComfyUI v0.22+)
2. Corrupted checkpoint file being loaded
3. Python/PyTorch memory leak

**Diagnosis:**
```powershell
# Check ComfyUI error output:
# If running in a terminal window, look for error messages like:
# "CUDA out of memory" → GPU memory issue
# "RuntimeError: CUDA device not available" → GPU driver issue
# "FileNotFoundError: model file not found" → Missing checkpoint

# Check system.log in ComfyUI directory:
ls "C:\Users\{user}\Documents\ComfyUI\system.log" -Tail 50

# Check if process is still running:
tasklist | findstr python  # Should show python.exe processes
```

**Fixes:**
1. **Restart ComfyUI**:
   ```powershell
   STOP.bat
   timeout /t 10  # Wait 10 seconds for full GPU release
   START.bat
   ```

2. **Verify checkpoint files integrity**:
   ```powershell
   # List all checkpoint files
   ls "C:\Users\{user}\Documents\ComfyUI\models\checkpoints\*" | Select Name, Length
   
   # If any file is 0 bytes, it's corrupted—delete it
   # Re-download from model repository (Hugging Face, CivitAI, etc.)
   ```

3. **Clear PyTorch cache**:
   ```powershell
   # Delete ComfyUI Python cache
   Remove-Item "C:\Users\{user}\Documents\ComfyUI\__pycache__" -Recurse -Force
   Remove-Item "C:\Users\{user}\Documents\ComfyUI\.venv\Lib\site-packages\__pycache__" -Recurse -Force
   ```

4. **If using face conditioning and CUDA is not installed**:
   - ReActor module fails with "cublasLt64_12.dll not found"
   - Install CUDA Toolkit 12.x from https://developer.nvidia.com/cuda-downloads
   - Restart ComfyUI after installation

---

### Symptom: "CUDA error: cublasLt64_12.dll missing" (face conditioning fails)

**Root cause:**
ReActor face-swap module requires CUDA Toolkit 12.x, which is not installed on the system.

**Diagnosis:**
```powershell
# Check if CUDA 12.x is installed:
ls "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.*"

# If directory doesn't exist, CUDA 12.x is not installed

# Check which CUDA version is installed:
ls "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v*"
# If only v11.x exists, upgrade to v12.x
```

**Fixes:**
1. **Install CUDA Toolkit 12.x** (permanent fix):
   - Download from https://developer.nvidia.com/cuda-downloads
   - Select Windows 11, x86_64, .exe (network)
   - Run installer with Admin privileges
   - Restart computer after installation

2. **Workaround: Disable face conditioning** (temporary):
   - When building decks, don't upload face photos
   - Cards will generate with art style but no face swapping
   - Once CUDA 12.x is installed, face conditioning will work automatically

---

### Symptom: Startup script fails with "Configuration validation failed"

**Root causes:**
1. paths_config.ps1 has syntax error or missing quotes
2. One of the required paths doesn't exist (e.g., Python not installed, ComfyUI missing)
3. PowerShell execution policy is too restrictive

**Diagnosis:**
```powershell
# Test paths_config.ps1 directly:
cd "C:\Users\{user}\Documents\mtg_deck_builder"
powershell -NoProfile -Command ". '.\paths_config.ps1'; Test-ConfigPaths"

# This should return $true if all paths are valid
# If it returns $false, one or more paths are missing

# Check individual paths:
powershell -NoProfile -Command ". '.\paths_config.ps1'; Write-Host $global:PythonExe; Write-Host $global:ComfyMainPy"

# Verify files exist:
Test-Path "C:\Python314\python.exe"  # Should be $true
Test-Path "E:\Games\comfy\ComfyUI\resources\ComfyUI\main.py"  # Should be $true
```

**Fixes:**
1. **Edit paths_config.ps1**: Update the 5 path variables to match your installation locations
   - `$global:PythonExe`: Path to Python 3.14 interpreter
   - `$global:ComfyPythonExe`: Path to ComfyUI venv Python
   - `$global:ComfyMainPy`: Path to ComfyUI main.py
   - `$global:ComfyBaseDir`: Path to ComfyUI base directory (where output/ lives)
   - `$global:DeckBuilderDir`: Path to mtg_deck_builder project

2. **Check syntax**: Open paths_config.ps1 in editor, verify all quotes and commas are balanced

3. **Fix missing installations**:
   - Python: Install from https://www.python.org/downloads/ (3.13+ required)
   - ComfyUI: See STARTUP_GUIDE.md → "Detailed Setup" section
   - Ollama: Install from https://ollama.ai/

---

## Service Health Checks

### Quick Health Check (run anytime)
```powershell
# Check all three services are running and responding:

echo "Checking Ollama..."
Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 -UseBasicParsing | Out-Null
if ($?) { Write-Host "✓ Ollama OK" } else { Write-Host "✗ Ollama FAILED" }

echo "Checking ComfyUI..."
Invoke-WebRequest -Uri "http://127.0.0.1:8188/system_stats" -TimeoutSec 2 -UseBasicParsing | Out-Null
if ($?) { Write-Host "✓ ComfyUI OK" } else { Write-Host "✗ ComfyUI FAILED" }

echo "Checking FastAPI..."
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/playstyles" -TimeoutSec 2 -UseBasicParsing | Out-Null
if ($?) { Write-Host "✓ FastAPI OK" } else { Write-Host "✗ FastAPI FAILED" }
```

### Service Logs
```powershell
# FastAPI server log:
ls -Path "C:\Users\{user}\Documents\mtg_deck_builder\server.log" -Tail 100

# ComfyUI system log (if available):
ls -Path "C:\Users\{user}\Documents\ComfyUI\system.log" -Tail 50

# Ollama logs (written to console, save if running in terminal)
```

---

## Performance Optimization

### GPU VRAM Optimization
Baseline: RTX 3090 (24GB) generates a single card in 10-35 seconds

**If generation is slow:**
1. Use SDXL instead of FLUX (faster but lower quality)
2. Reduce batch size in server.py: `batch_size = 5` instead of `10`
3. Use lower image resolution: 512x512 instead of 1024x1024

**If GPU memory is exhausted:**
1. Stop all other GPU applications (Chrome, games, video editors)
2. Reduce number of simultaneous generations
3. Restart ComfyUI to clear GPU cache: `STOP.bat` → `START.bat`

### Disk Optimization
Baseline: SSD (NVMe) generates images in normal timeframe; HDD may be 2-3x slower

**If saving images is slow:**
1. Move ComfyUI output directory to SSD if it's on HDD
2. Check disk free space (need >50GB free for normal operation)
3. Defragment HDD (if using HDD): `Defrag-Volume -DriveLetter C -Defrag`

### Network Optimization
**If Ollama is slow or unresponsive:**
1. Restart Ollama: `STOP.bat` → `START.bat`
2. Check network connectivity: `ping 127.0.0.1` should respond instantly
3. Reduce number of simultaneous API calls to Ollama
4. Increase Ollama timeout in server.py if needed

---

## Adding New Features

### Adding a New Art Style

**Steps:**
1. Create new preset in `image_gen.py`:
   ```python
   "my_style": {
       "flux_prefix": "Render in my style with these characteristics...",
       "negative_prompt": "Things to avoid...",
       "lora_weights": {"style_lora": 0.7},
       "model": "flux"
   }
   ```

2. Test the style by generating 1 card
3. Update `image_gen.py` docstring listing all available styles
4. Update `README.md` → "Available Art Styles" section with example output
5. Commit change with message: "Add 'my_style' art style for card generation"

### Adding a New LoRA Model

**Steps:**
1. Download LoRA from CivitAI or HuggingFace
2. Place in `C:\Users\{user}\Documents\ComfyUI\models\loras\{name}.safetensors`
3. Update `image_gen.py` AVAILABLE_LORAS list:
   ```python
   AVAILABLE_LORAS = {
       "new_lora": ("new_lora.safetensors", 0.7),  # (filename, default_weight)
       # ... existing entries ...
   }
   ```

4. Test by using new LoRA in deck builder UI
5. Update README.md → "Available LoRAs" with description and usage
6. Commit: "Add new_lora model for enhanced artistic rendering"

### Adding a New Configururation Option

**Steps:**
1. Add variable to `paths_config.ps1` (if it's a path or port)
   - Or add to `server.py` as environment variable
2. Update `STARTUP_GUIDE.md` → "Configuration" section explaining the new option
3. Update `README.md` → "Configuration" section if it's user-facing
4. Update `DEVELOPMENT_GUIDELINES.md` → "Documentation Update Requirements" if it's a new change type
5. Test the new option works end-to-end
6. Commit: "Add configuration option for [feature]"

---

## Version Updates and Dependencies

### Updating Python Packages

**When to update:**
- Monthly check for critical security updates
- Before major feature work, to ensure latest bug fixes
- Only if a bug is blocking development

**How to update:**
```powershell
# List all installed packages:
pip list

# Update a single package:
pip install --upgrade package_name

# Update all packages (risky, may break compatibility):
pip install --upgrade pip
pip install --upgrade -r requirements.txt
```

**After updating:**
- Run full startup test: `START.bat` → verify all services start
- Generate 1 card to verify compatibility
- Check server.log for warnings
- Commit with message: "Update [package] to version X.Y.Z"

### Updating ComfyUI

**When to update:**
- Every 2-3 months to get bug fixes and performance improvements
- Only if a specific bug is fixed that you need

**How to update:**
```powershell
# Backup current ComfyUI
Copy-Item "C:\Users\{user}\Documents\ComfyUI" "C:\Users\{user}\Documents\ComfyUI.backup"

# Update ComfyUI from GitHub (if installed via git):
cd "C:\Users\{user}\Documents\ComfyUI"
git pull origin main

# Reinstall dependencies:
.\.venv\Scripts\pip install -r requirements.txt

# Test:
.\.venv\Scripts\python main.py
# Wait for startup, then kill with Ctrl+C
```

**If update breaks something:**
```powershell
# Restore backup:
Remove-Item "C:\Users\{user}\Documents\ComfyUI"
Rename-Item "C:\Users\{user}\Documents\ComfyUI.backup" "ComfyUI"
```

### Updating NVIDIA Drivers and CUDA

**When to update:**
- Only if a specific CUDA feature is required (e.g., ReActor needs CUDA 12.x)
- Or if NVIDIA releases critical security fix

**How to update:**
1. Download latest NVIDIA driver from https://www.nvidia.com/Download/driverDetails.aspx
2. Download CUDA Toolkit from https://developer.nvidia.com/cuda-downloads
3. Run both installers with Admin privileges
4. Restart computer
5. Test: Run `nvidia-smi` and verify CUDA Capability is 8.0+

**After updating:**
- Restart `START.bat` to reconnect to GPU
- Generate 1 card to verify GPU is detected
- Check for any "driver" warnings in server.log

---

## Monitoring and Logging

### Enabling Debug Logging

In `server.py`, uncomment this line:
```python
logging.basicConfig(level=logging.DEBUG)  # Change from INFO to DEBUG
```

This will output detailed information about each request and operation. Warning: Creates very large log files, only use for troubleshooting.

### Monitoring in Real-Time

**Watch server log as it happens:**
```powershell
# Open PowerShell and run:
Get-Content "C:\Users\{user}\Documents\mtg_deck_builder\server.log" -Wait -Tail 20
# This shows last 20 lines and updates as new logs arrive
# Press Ctrl+C to stop
```

**Monitor GPU usage during generation:**
```powershell
# Open NVIDIA App or Task Manager
# Go to Performance → GPU
# Watch memory usage as cards generate
# Should peak at 15-20GB for a 24GB card, not 23GB+
```

---

## Contact and Support

If you encounter an issue not covered in this guide:

1. **Check the logs**: `server.log`, ComfyUI system.log, and Ollama output
2. **Review STARTUP_GUIDE.md**: Detailed troubleshooting for startup issues
3. **Review DEVELOPMENT_GUIDELINES.md**: Code patterns and best practices
4. **Search code for TODO/FIXME**: May reveal known issues and planned fixes

For unresolved issues, document:
- Exact error message (copy from logs)
- When it happens (after startup, during generation, etc.)
- What you were trying to do
- Your hardware (GPU, RAM, SSD/HDD)
- Output of `nvidia-smi` command
