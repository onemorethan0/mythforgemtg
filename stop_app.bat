@echo off
setlocal enabledelayedexpansion
title MTG Commander Deck Builder - Shutdown
color 0C

echo ============================================
echo  MTG Commander Deck Builder - Stopping
echo ============================================
echo.

:: ── 1. FastAPI (Python running server.py or uvicorn) ─────────────────────────
echo [1/3] Stopping FastAPI server...
powershell -NoProfile -Command ^
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'server\.py|uvicorn.*server:app' } | ForEach-Object { Write-Host ('       Killing PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
:: Also kill the wrapping cmd.exe window started by start_app.bat
taskkill /FI "WINDOWTITLE eq MTG Deck Builder API" /F >nul 2>&1
echo       Done.
echo.

:: ── 2. ComfyUI ────────────────────────────────────────────────────────────────
echo [2/3] Stopping ComfyUI...
powershell -NoProfile -Command ^
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*ComfyUI*main.py*' } | ForEach-Object { Write-Host ('       Killing PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo       Done.
echo.

:: ── 3. Ollama ─────────────────────────────────────────────────────────────────
echo [3/3] Stopping Ollama...
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | findstr /I "ollama.exe" >nul
if %errorlevel% == 0 (
    taskkill /IM ollama.exe /F >nul 2>&1
    echo       Done.
) else (
    echo       Ollama was not running.
)
echo.

:: ── Verify ports are released ────────────────────────────────────────────────
timeout /t 2 /nobreak >nul 2>&1
set "still_running="
for %%P in (8000 8188 11434) do (
    netstat -ano 2>nul | findstr ":%%P " | findstr "LISTENING" >nul && (
        set "still_running=!still_running! %%P"
    )
)
if defined still_running (
    echo  WARNING: Ports!still_running! still in use. Some processes may not have stopped.
) else (
    echo  All ports released.
)

echo ============================================
echo  All services stopped. VRAM freed.
echo ============================================
timeout /t 3 /nobreak >nul 2>&1
endlocal
