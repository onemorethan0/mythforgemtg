@echo off
REM ═══════════════════════════════════════════════════════════════════════════════
REM MTG Commander Deck Builder — Shutdown Script
REM
REM Gracefully stops all three services and releases GPU/system resources:
REM   1. FastAPI Server (deck builder backend)
REM   2. ComfyUI (image generation engine)
REM   3. Ollama (LLM backend)
REM
REM This script also verifies that ports are released for the next startup.
REM ═══════════════════════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion
title MTG Commander Deck Builder - Shutdown
color 0C

echo.
echo ════════════════════════════════════════════════════════
echo   MTG Commander Deck Builder — Stopping Services
echo ════════════════════════════════════════════════════════
echo.

REM ── 1. FastAPI Server ──────────────────────────────────────────────────────────
echo [1/3] Stopping FastAPI server...
powershell -NoProfile -Command ^
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'server\.py|uvicorn.*server:app' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
taskkill /FI "WINDOWTITLE eq MTG Deck Builder API" /F >nul 2>&1
echo        ✓ FastAPI stopped
echo.

REM ── 2. ComfyUI ─────────────────────────────────────────────────────────────────
echo [2/3] Stopping ComfyUI...
powershell -NoProfile -Command ^
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*ComfyUI*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo        ✓ ComfyUI stopped (GPU memory freed)
echo.

REM ── 3. Ollama ──────────────────────────────────────────────────────────────────
echo [3/3] Stopping Ollama...
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | findstr /I "ollama.exe" >nul
if %errorlevel% == 0 (
    taskkill /IM ollama.exe /F >nul 2>&1
    echo        ✓ Ollama stopped
) else (
    echo        (Ollama was not running)
)
echo.

REM ── Verify Ports Released ──────────────────────────────────────────────────────
timeout /t 2 /nobreak >nul 2>&1
set "still_running="
for %%P in (8000 8188 11434) do (
    netstat -ano 2>nul | findstr ":%%P " | findstr "LISTENING" >nul && (
        set "still_running=!still_running! %%P"
    )
)
if defined still_running (
    echo [WARNING] Ports!still_running! still in use — some processes may not have stopped cleanly
    echo           Waiting 5 seconds before retrying...
    timeout /t 5 /nobreak >nul 2>&1
    taskkill /F /IM python.exe >nul 2>&1
    taskkill /F /IM ollama.exe >nul 2>&1
    timeout /t 2 /nobreak >nul 2>&1
    echo           Retry complete.
) else (
    echo [✓] All ports released successfully
)

echo.
echo ════════════════════════════════════════════════════════
echo   All services stopped. System resources freed.
echo ════════════════════════════════════════════════════════
echo.
endlocal
