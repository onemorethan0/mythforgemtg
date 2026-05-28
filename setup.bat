@echo off
REM First-time setup script
REM This is a shortcut to: manage.bat → Option 6

echo.
echo ============================================
echo     MYTH FORGE - First-Time Setup
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
echo ============================================
echo [OK] Setup complete!
echo ============================================
echo.
echo Next steps:
echo   1. Download models: manage.bat (option 7)
echo   2. Start server: dev.bat
echo   3. Open browser: http://localhost:8000
echo.
pause
