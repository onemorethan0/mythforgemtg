@echo off
REM Myth Forge Installer for Windows
REM This script installs and configures the MTG Commander Deck Builder

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ================================================================
echo   MYTH FORGE INSTALLER
echo   MTG Commander Deck Builder
echo ================================================================
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.8+ from https://www.python.org
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [OK] Python found
python --version

REM Check for Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found!
    echo Please install Node.js from https://nodejs.org
    pause
    exit /b 1
)

echo [OK] Node.js found
node --version
npm --version

echo.
echo Installing Python dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install Python dependencies
    pause
    exit /b 1
)

echo.
echo Installing frontend dependencies...
cd frontend
call npm install
if errorlevel 1 (
    echo ERROR: Failed to install npm dependencies
    pause
    exit /b 1
)

echo.
echo Building frontend...
call npm run build
if errorlevel 1 (
    echo ERROR: Failed to build frontend
    pause
    exit /b 1
)

cd ..

echo.
echo Creating directories...
if not exist "data" mkdir data
if not exist "renders" mkdir renders
if not exist "scryfall_cache" mkdir scryfall_cache

echo.
echo.
echo ================================================================
echo   INSTALLATION COMPLETE!
echo ================================================================
echo.
echo To start the server, run:
echo   python server.py
echo.
echo Then open your browser to:
echo   http://localhost:8000
echo.
echo Optional but recommended:
echo   - Install Ollama for better card theming
echo   - Install ComfyUI for image generation
echo   - See README.md for full setup guide
echo.
echo ================================================================
echo.

set /p start_server="Start the server now? (y/n): "
if /i "%start_server%"=="y" (
    python server.py
) else (
    echo You can start the server anytime by running: python server.py
    pause
)
