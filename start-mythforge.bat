@echo off
REM Myth Forge Startup Script for Windows

cd /d "%~dp0"

echo.
echo ====================================
echo  MYTH FORGE SERVER STARTING
echo ====================================
echo.
echo Open your browser to: http://localhost:8000
echo.
echo Press Ctrl+C to stop the server
echo.

python server.py
