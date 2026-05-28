@echo off
REM Kill all Python processes running Myth Forge and ComfyUI servers

echo.
echo ============================================
echo  MYTH FORGE - Kill Background Servers
echo ============================================
echo.

REM Find and kill Python processes listening on ports 8000 (Myth Forge) and 8188 (ComfyUI)

echo Checking for running servers...
echo.

REM Kill Myth Forge (port 8000)
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000" ^| find "LISTENING"') do (
  echo [INFO] Killing process %%a (port 8000 - Myth Forge)
  taskkill /PID %%a /F /T >nul 2>&1
)

REM Kill ComfyUI (port 8188)
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8188" ^| find "LISTENING"') do (
  echo [INFO] Killing process %%a (port 8188 - ComfyUI)
  taskkill /PID %%a /F /T >nul 2>&1
)

REM Alternative: Kill all python.exe processes (more aggressive)
echo.
echo Cleaning up orphaned Python processes...
taskkill /IM python.exe /F /T >nul 2>&1

echo.
echo [OK] Server cleanup complete
echo.
pause
