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
echo.
echo   0. Exit
echo.

set /p choice="Choose an option (0-8): "

if "%choice%"=="1" goto start_dev
if "%choice%"=="2" goto start_clean
if "%choice%"=="3" goto check_status
if "%choice%"=="4" goto stop_server
if "%choice%"=="5" goto cleanup
if "%choice%"=="6" goto setup
if "%choice%"=="7" goto download_models
if "%choice%"=="8" goto rebuild_frontend
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

:exit_menu
exit /b 0
