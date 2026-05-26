@echo off
REM ═══════════════════════════════════════════════════════════════════════════════
REM MTG Commander Deck Builder — Full Startup Script
REM
REM This script starts all three required services in the correct order:
REM   1. Ollama (LLM backend for card theming)
REM   2. ComfyUI (AI art generation engine)
REM   3. FastAPI Server (deck builder backend + React frontend)
REM
REM The script checks each service for readiness before moving to the next,
REM automatically starts missing services, and opens your browser when ready.
REM
REM BEFORE RUNNING:
REM   • Edit paths_config.ps1 if your services are in different locations
REM   • ComfyUI and Ollama can be running or stopped (this script will handle it)
REM
REM To stop all services, run: STOP.bat
REM ═══════════════════════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion
title MTG Commander Deck Builder - Startup
color 0A

echo.
echo ════════════════════════════════════════════════════════
echo   MTG Commander Deck Builder — Starting Services
echo ════════════════════════════════════════════════════════
echo.

REM Load configuration from paths_config.ps1
cd /d "%~dp0"
powershell -NoProfile -Command ^
    ". '.\paths_config.ps1'; if(-not (Test-ConfigPaths)){exit 1}"
if %errorlevel% neq 0 (
    echo [ERROR] Configuration validation failed. Check paths_config.ps1
    pause
    exit /b 1
)

REM ── 1. Ollama ──────────────────────────────────────────────────────────────────
echo [1/3] Checking Ollama (LLM backend)...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 (
    echo        ✓ Already running
    goto :ollama_ok
)
echo        Starting Ollama (this may take 5-10 seconds)...
start "Ollama Server" /min "C:\Users\rvn92\AppData\Local\Programs\Ollama\ollama.exe" serve
set /a tries=0
:wait_ollama
timeout /t 2 /nobreak >nul 2>&1
set /a tries+=1
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 goto :ollama_ok
if %tries% geq 15 goto :ollama_fail
goto :wait_ollama
:ollama_fail
echo        [✗ FAILED] Ollama did not respond after 30 seconds
echo        Check if Ollama is installed and try: ollama serve
pause
exit /b 1
:ollama_ok
echo        ✓ Ollama ready
echo.

REM ── 2. ComfyUI ─────────────────────────────────────────────────────────────────
echo [2/3] Checking ComfyUI (image generation engine)...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 (
    echo        ✓ Already running
    goto :comfy_ok
)
echo        Starting ComfyUI (this may take 30-60 seconds)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0\launch_comfyui.ps1" >nul 2>&1
if %errorlevel% neq 0 (
    echo        [✗ FAILED] ComfyUI startup failed
    echo        Check launch_comfyui.ps1 configuration
    pause
    exit /b 1
)
echo        Waiting for ComfyUI to initialize...
set /a tries=0
:wait_comfy
timeout /t 3 /nobreak >nul 2>&1
set /a tries+=1
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 goto :comfy_ok
if %tries% geq 30 goto :comfy_fail
goto :wait_comfy
:comfy_fail
echo        [✗ FAILED] ComfyUI did not respond after 90 seconds
pause
exit /b 1
:comfy_ok
echo        ✓ ComfyUI ready
echo.

REM ── 3. FastAPI Server ──────────────────────────────────────────────────────────
echo [3/3] Starting FastAPI server (deck builder backend)...

REM Kill anything on port 8000
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%p >nul 2>&1
)
timeout /t 2 /nobreak >nul 2>&1

start "MTG Deck Builder API" /min cmd /c "cd /d %~dp0 && set PYTHONIOENCODING=utf-8 && C:\Python314\python.exe server.py >> server.log 2>&1"
echo        Waiting for API to come up...
set /a tries=0
:wait_api
timeout /t 2 /nobreak >nul 2>&1
set /a tries+=1
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/playstyles' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 goto :api_ok
if %tries% geq 15 goto :api_fail
goto :wait_api
:api_fail
echo        [✗ FAILED] FastAPI did not respond after 30 seconds
echo        Check server.log for startup errors
pause
exit /b 1
:api_ok
echo        ✓ FastAPI server ready
echo.

REM ── All Services Running ───────────────────────────────────────────────────────
echo ════════════════════════════════════════════════════════
echo   ✓ All services started successfully!
echo ════════════════════════════════════════════════════════
echo.
echo   App URL:       http://localhost:8000
echo   ComfyUI:       http://localhost:8188
echo   Ollama:        http://localhost:11434
echo.
timeout /t 2 /nobreak >nul 2>&1
start "" "http://localhost:8000"
echo Opening browser... Press any key to close this window (services keep running)
pause >nul
endlocal
