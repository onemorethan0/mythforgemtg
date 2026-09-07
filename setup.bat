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
echo   1. Download AI models (optional): manage.bat (option 8)
echo   2. Download deck-strength data (optional): manage.bat (option 10)
echo   3. Start server: dev.bat
echo   4. Open browser: http://localhost:8000
echo.
pause
