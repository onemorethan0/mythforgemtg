@echo off
setlocal enabledelayedexpansion

REM Direct commands (skip the menu): manage.bat start | status | stop
if /i "%~1"=="start"  goto start_dev
if /i "%~1"=="status" goto check_status
if /i "%~1"=="stop"   goto stop_server

:menu
cls
echo ============================================
echo      MYTH FORGE  -  Server Manager
echo ============================================
echo.
echo   -- Run --
echo     1.  Start server          (daily use; serves the app on :8000)
echo     2.  Clean start           (kill a stale :8000 process, then start)
echo     3.  Start ComfyUI         (image-generation backend on :8188)
echo.
echo   -- Manage --
echo     4.  Check status          (ComfyUI :8188, llama-swap :8010, strength :8020, Myth Forge :8000)
echo     5.  Stop server           (free :8000)
echo     6.  Kill orphaned Python  (force-stop ALL python.exe)
echo.
echo   -- Setup --
echo     7.  First-time setup      (install deps, then build the UI)
echo     8.  Download AI models
echo     9.  Rebuild frontend      (after UI changes)
echo.
echo     0.  Exit
echo.
set "choice="
set /p choice="Choose an option (0-9): "

if "%choice%"=="1" goto start_dev
if "%choice%"=="2" goto start_clean
if "%choice%"=="3" goto start_comfyui
if "%choice%"=="4" goto check_status
if "%choice%"=="5" goto stop_server
if "%choice%"=="6" goto cleanup
if "%choice%"=="7" goto setup
if "%choice%"=="8" goto download_models
if "%choice%"=="9" goto rebuild_frontend
if "%choice%"=="0" goto exit_menu

echo.
echo [WARN] Invalid choice "%choice%" - enter a number from 0 to 9.
timeout /t 2 >nul
goto menu

:start_dev
cls
echo ============================================
echo      MYTH FORGE  -  Start Server
echo ============================================
echo.
echo [*] Backend services:
echo       llama-swap  :8010   theming   (this script starts it below)
echo       strength    :8020   deck analysis  (this script starts it below)
echo       ComfyUI     :8188   art       (start separately - menu option 3)
echo.
call :ensure_llama
call :ensure_gauntlet
echo.
echo [*] Starting Myth Forge on http://127.0.0.1:8000
echo [*] Leave this window open; press Ctrl+C to stop the server.
echo.
python server.py
echo.
echo [OK] Server stopped.
pause
goto menu

:start_clean
cls
echo ============================================
echo      MYTH FORGE  -  Clean Start
echo ============================================
echo.
echo [*] Freeing port 8000 (killing any stale server)...
set "_killed="
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":8000" ^| find "LISTENING"') do (
  echo       [*] Killing PID %%a
  taskkill /PID %%a /F /T >nul 2>&1
  set "_killed=1"
)
if not defined _killed echo       [OK] Nothing was listening on :8000.
timeout /t 2 >nul
echo.
call :ensure_llama
call :ensure_gauntlet
echo.
echo [*] Starting Myth Forge on http://127.0.0.1:8000
echo [*] Leave this window open; press Ctrl+C to stop the server.
echo.
python server.py
echo.
echo [OK] Server stopped.
pause
goto menu

:start_comfyui
cls
echo ============================================
echo      MYTH FORGE  -  Start ComfyUI
echo ============================================
echo.
netstat -aon 2>nul | find ":8188" | find "LISTENING" >nul
if !errorlevel! equ 0 (
  echo [OK] ComfyUI is already running on :8188.
  echo.
  pause
  goto menu
)
REM Launch the SAME ComfyUI the server uses. server._resolve_comfyui_cmd() is the
REM single source of truth: it auto-detects the Desktop install + its CUDA venv
REM (reading %APPDATA%\ComfyUI\config.json) and uses NORMAL_VRAM + the offload fix.
echo [*] Locating and starting ComfyUI via the server's resolver...
echo [*] Cold start loads the 3D nodes + DB migration (~3-4 min); warm start ~30s.
echo [*] This blocks until ComfyUI is ready - please be patient.
echo.
python -c "import server, sys; sys.exit(0 if server._ensure_comfyui_ready(wait_timeout=300) else 1)"
if !errorlevel! equ 0 (
  echo.
  echo [OK] ComfyUI is ready on :8188.
) else (
  echo.
  echo [X] ComfyUI failed to start. Check renders\comfyui_startup.log for the
  echo     backend's own output, then start ComfyUI Desktop manually if needed.
)
echo.
pause
goto menu

:check_status
cls
echo ============================================
echo      MYTH FORGE  -  Status
echo ============================================
echo.
call :status_line "ComfyUI      :8188" 8188 ""
call :status_line "llama-swap   :8010" 8010 "starts with the server - menu option 1 or 2"
call :status_line "strength API :8020" 8020 "starts with the server - deck analysis falls back to heuristic"
call :status_line "Myth Forge   :8000" 8000 ""
echo.
pause
goto menu

:stop_server
cls
echo ============================================
echo      MYTH FORGE  -  Stop Server
echo ============================================
echo.
echo [*] Stopping Myth Forge (port 8000)...
set "_killed="
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":8000" ^| find "LISTENING"') do (
  echo       [*] Killing PID %%a
  taskkill /PID %%a /F /T >nul 2>&1
  set "_killed=1"
)
if defined _killed (
  echo [OK] Server stopped.
) else (
  echo [OK] Server was not running.
)
echo.
pause
goto menu

:cleanup
cls
echo ============================================
echo      MYTH FORGE  -  Kill Orphaned Python
echo ============================================
echo.
echo [WARN] This force-stops ALL python.exe processes, including any unrelated
echo        Python apps. Use it only to clear a stuck Myth Forge.
echo.
taskkill /IM python.exe /F /T >nul 2>&1
if !errorlevel! equ 0 (
  echo [OK] Python processes terminated.
) else (
  echo [OK] No python.exe processes were running.
)
echo.
pause
goto menu

:setup
cls
echo ============================================
echo      MYTH FORGE  -  First-Time Setup
echo ============================================
echo.
echo [*] Installing Python dependencies...
python -m pip install -r requirements.txt
echo.
echo [*] Installing frontend dependencies...
pushd frontend
call npm install
echo.
echo [*] Building frontend...
call npm run build
popd
echo.
echo [OK] Setup complete - use option 1 to start the server.
echo.
pause
goto menu

:download_models
cls
echo ============================================
echo      MYTH FORGE  -  Download AI Models
echo ============================================
echo.
echo [*] Launching the model downloader...
echo.
python download-models.py
echo.
echo [OK] Done.
pause
goto menu

:rebuild_frontend
cls
echo ============================================
echo      MYTH FORGE  -  Rebuild Frontend
echo ============================================
echo.
echo [*] Building frontend...
pushd frontend
call npm run build
popd
echo.
echo [OK] Frontend rebuilt.
echo [WARN] Hard-refresh the browser to load it (Ctrl+Shift+R).
echo.
pause
goto menu

:exit_menu
exit /b 0

REM ---- helpers (reached only via CALL) ----------------------------------------
:ensure_llama
REM Make sure the llama-swap LLM gateway (:8010) is running; start it if not.
REM The boot Startup-folder shortcut was removed - manage.bat owns startup now.
netstat -aon 2>nul | find ":8010" | find "LISTENING" >nul
if !errorlevel! equ 0 (
  echo [OK] llama-swap LLM gateway already running on :8010.
  goto :eof
)
if not exist "E:\llama\start-llama-swap.bat" (
  echo [X] llama-swap launcher missing: E:\llama\start-llama-swap.bat
  echo     Theming needs the :8010 gateway - start it manually.
  goto :eof
)
echo [*] Starting llama-swap LLM gateway (:8010) in its own window...
start "llama-swap" /min /d "E:\llama" cmd /c "E:\llama\start-llama-swap.bat"
set "_ll="
for /l %%i in (1,1,20) do (
  if not defined _ll (
    timeout /t 1 /nobreak >nul
    netstat -aon 2>nul | find ":8010" | find "LISTENING" >nul
    if !errorlevel! equ 0 set "_ll=1"
  )
)
if defined _ll (
  echo [OK] llama-swap is up on :8010.
) else (
  echo [WARN] llama-swap not ready yet - it may still be starting in its own window.
)
goto :eof

:ensure_gauntlet
REM Make sure the MythGauntlet strength API (:8020) is running; start it if not.
REM The engine now lives IN THIS REPO (src\mythgauntlet) - it is started as a separate
REM process on purpose: it holds the whole card-semantics store in memory (~50s cold,
REM ~1.4s warm), and folding that into the web server would make every Forge restart
REM pay for it. The Analyze panel reports "unavailable" until it is up.
netstat -aon 2>nul | find ":8020" | find "LISTENING" >nul
if !errorlevel! equ 0 (
  echo [OK] MythGauntlet strength API already running on :8020.
  goto :eof
)
if not exist "%~dp0src\mythgauntlet\__main__.py" (
  echo [WARN] Engine missing at src\mythgauntlet - the Analyze panel will report
  echo        bracket/strength as unavailable.
  goto :eof
)
echo [*] Starting the strength API (:8020) from src\mythgauntlet in its own window...
start "mythgauntlet-serve" /min /d "%~dp0" cmd /c "set PYTHONPATH=%~dp0src&& python -m mythgauntlet serve"
set "_mg="
for /l %%i in (1,1,15) do (
  if not defined _mg (
    timeout /t 1 /nobreak >nul
    netstat -aon 2>nul | find ":8020" | find "LISTENING" >nul
    if !errorlevel! equ 0 set "_mg=1"
  )
)
if defined _mg (
  echo [OK] Strength API is up on :8020.
) else (
  echo [*] Strength API still warming ^(cold store load ~50s^) - the Analyze panel
  echo     uses the heuristic until it is ready.
)
goto :eof

:status_line
REM  %~1 = label   %~2 = port   %~3 = hint shown when stopped (optional)
netstat -aon 2>nul | find ":%~2" | find "LISTENING" >nul
if !errorlevel! equ 0 (
  set "_pid="
  for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":%~2" ^| find "LISTENING"') do set "_pid=%%a"
  echo   [ RUNNING ]   %~1   PID !_pid!
) else (
  if "%~3"=="" (
    echo   [ STOPPED ]   %~1
  ) else (
    echo   [ STOPPED ]   %~1   ^(%~3^)
  )
)
goto :eof
