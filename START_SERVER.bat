@echo off
REM Commander Deck Builder Startup Script
REM This script starts the server with proper startup checks

echo.
echo ========================================
echo   MTG Commander Deck Builder
echo ========================================
echo.
echo Checking for required services...
echo.

REM Check if Ollama is reachable (simple HTTP check)
powershell -Command "try { $null = (Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 -ErrorAction Stop); Write-Host '[OK] Ollama is running' -ForegroundColor Green } catch { Write-Host '[ERROR] Ollama is not running!' -ForegroundColor Red; Write-Host '        Start Ollama first: ollama serve' -ForegroundColor Yellow }"

echo.
echo Starting deck builder server...
echo.

cd /d "%~dp0"
python server.py

pause
