@echo off
REM Start Myth Forge after killing any existing instances (but NOT ComfyUI)

echo.
echo ============================================
echo  MYTH FORGE - Clean Start
echo ============================================
echo.

echo [*] Killing existing Myth Forge instances on port 8000...

REM Kill only the Myth Forge server process on port 8000 (not ComfyUI on 8188)
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000" ^| find "LISTENING"') do (
  echo [*] Killing PID %%a (port 8000)
  taskkill /PID %%a /F /T >nul 2>&1
)

echo [*] Waiting for cleanup...
timeout /t 2 /nobreak >nul

echo [*] Starting Myth Forge server...
echo [*] (Make sure ComfyUI is already running on port 8188)
echo.

REM Start the server
python server.py

pause
