@echo off
setlocal enabledelayedexpansion

:menu
cls
echo.
echo ============================================
echo     MYTH FORGE - Server Management
echo ============================================
echo.
echo Select an option:
echo.
echo   1. Start Development Server (recommended daily use)
echo   2. Clean Start (kill old processes, then start fresh)
echo   3. Check Server Status (ComfyUI, Ollama, Myth Forge)
echo   4. Stop Myth Forge Server
echo   5. Clean Up Orphaned Processes
echo   6. First-Time Setup (install dependencies)
echo   7. Download AI Models
echo   8. Rebuild Frontend
echo   9. Start ComfyUI (image generation backend)
echo.
echo   0. Exit
echo.

set /p choice="Choose an option (0-9): "

if "%choice%"=="1" goto start_dev
if "%choice%"=="2" goto start_clean
if "%choice%"=="3" goto check_status
if "%choice%"=="4" goto stop_server
if "%choice%"=="5" goto cleanup
if "%choice%"=="6" goto setup
if "%choice%"=="7" goto download_models
if "%choice%"=="8" goto rebuild_frontend
if "%choice%"=="9" goto start_comfyui
if "%choice%"=="0" goto exit_menu

echo Invalid choice. Please try again.
timeout /t 2 >nul
goto menu

:start_dev
cls
echo.
echo [*] Starting Myth Forge Development Server...
echo [*] Make sure ComfyUI is running on port 8188
echo.
python server.py
pause
goto menu

:start_clean
cls
echo.
echo [*] Cleaning up old Myth Forge processes...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":8000" ^| find "LISTENING"') do (
  echo [*] Killing PID %%a
  taskkill /PID %%a /F /T >nul 2>&1
)
timeout /t 2 >nul
echo [*] Starting fresh Myth Forge server...
echo.
python server.py
pause
goto menu

:check_status
cls
echo.
echo ============================================
echo     Server Status Check
echo ============================================
echo.

echo ComfyUI (port 8188):
netstat -aon 2>nul | find ":8188" | find "LISTENING" >nul
if !errorlevel! equ 0 (
  for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":8188" ^| find "LISTENING"') do (
    echo   ✓ RUNNING (PID: %%a)
  )
) else (
  echo   ✗ NOT RUNNING
)

echo.
echo Myth Forge (port 8000):
netstat -aon 2>nul | find ":8000" | find "LISTENING" >nul
if !errorlevel! equ 0 (
  for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":8000" ^| find "LISTENING"') do (
    echo   ✓ RUNNING (PID: %%a)
  )
) else (
  echo   ✗ NOT RUNNING
)

echo.
echo Ollama (port 11434):
netstat -aon 2>nul | find ":11434" | find "LISTENING" >nul
if !errorlevel! equ 0 (
  for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":11434" ^| find "LISTENING"') do (
    echo   ✓ RUNNING (PID: %%a)
  )
) else (
  echo   ✗ NOT RUNNING
)

echo.
echo.
pause
goto menu

:stop_server
cls
echo.
echo [*] Stopping Myth Forge server (port 8000)...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":8000" ^| find "LISTENING"') do (
  echo [*] Killing PID %%a
  taskkill /PID %%a /F /T >nul 2>&1
)
echo [OK] Done
echo.
pause
goto menu

:cleanup
cls
echo.
echo [*] Cleaning up orphaned Python processes...
taskkill /IM python.exe /F /T >nul 2>&1
echo [OK] Cleanup complete
echo.
pause
goto menu

:setup
cls
echo.
echo ============================================
echo     First-Time Setup
echo ============================================
echo.
echo [*] Installing Python dependencies...
python -m pip install -r requirements.txt
echo.
echo [*] Installing frontend dependencies...
cd frontend
call npm install
cd ..
echo.
echo [*] Building frontend...
cd frontend
call npm run build
cd ..
echo.
echo [OK] Setup complete
echo.
pause
goto menu

:download_models
cls
echo.
echo ============================================
echo     Download AI Models
echo ============================================
echo.
echo Starting model downloader...
echo.
python download-models.py
pause
goto menu

:rebuild_frontend
cls
echo.
echo [*] Rebuilding frontend...
cd frontend
call npm run build
cd ..
echo.
echo [OK] Frontend rebuilt
echo [*] Remember to hard refresh browser (Ctrl+Shift+R)
echo.
pause
goto menu

:start_comfyui
cls
echo.
echo ============================================
echo     Start ComfyUI
echo ============================================
echo.

REM Check if already running
netstat -aon 2>nul | find ":8188" | find "LISTENING" >nul
if !errorlevel! equ 0 (
  echo   [OK] ComfyUI is already running on port 8188
  echo.
  pause
  goto menu
)

REM Launch the SAME ComfyUI the server uses. The old code guessed paths and
REM started a stale separate clone (C:\Users\%USERNAME%\ComfyUI) with the wrong
REM base directory, which refused to start. server._resolve_comfyui_cmd() is the
REM single source of truth: it auto-detects the Desktop install + its CUDA venv
REM (reading %APPDATA%\ComfyUI\config.json) and uses NORMAL_VRAM + the offload fix.
echo   [*] Locating + starting ComfyUI (via the server's resolver)...
echo   [*] Cold start loads the 3D nodes + DB migration (~3-4 min); warm start ~30s.
echo   [*] This waits for it — please be patient on the first launch.
echo.
python -c "import server, sys; sys.exit(0 if server._ensure_comfyui_ready(wait_timeout=300) else 1)"
if !errorlevel! equ 0 (
  echo.
  echo   [OK] ComfyUI is ready on port 8188.
) else (
  echo.
  echo   [!] ComfyUI failed to start. See renders\comfyui_startup.log for the
  echo       backend's own output, then start ComfyUI Desktop manually if needed.
)
echo.
pause
goto menu

:exit_menu
exit /b 0
