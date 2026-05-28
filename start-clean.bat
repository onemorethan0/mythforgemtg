@echo off
REM Start Myth Forge after killing any existing instances

echo.
echo ============================================
echo  MYTH FORGE - Clean Start
echo ============================================
echo.

echo [*] Killing existing server instances...
taskkill /IM python.exe /F /T >nul 2>&1

echo [*] Waiting for cleanup...
timeout /t 2 /nobreak >nul

echo [*] Starting Myth Forge server...
echo.

REM Start the server
python server.py

pause
