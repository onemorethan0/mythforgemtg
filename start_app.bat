@echo off
setlocal enabledelayedexpansion
title MTG Commander Deck Builder - Startup
color 0A

echo ============================================
echo  MTG Commander Deck Builder - Starting Up
echo ============================================
echo.

:: ── 0. Complete any pending model downloads ──────────────────────────────────
powershell -NoProfile -Command "$j=Get-BitsTransfer -Name 'FLUX1-dev-fp8' -EA SilentlyContinue; if($j -and $j.JobState -eq 'Transferred'){$j|Complete-BitsTransfer; Write-Host '  flux1-dev-fp8.safetensors download committed to disk.'} elseif($j){Write-Host ('  FLUX dev download in progress: '+[math]::Round($j.BytesTransferred/$j.BytesTotal*100,1)+'%')}"
echo.

:: ── 1. Ollama ─────────────────────────────────────────────────────────────────
echo [1/3] Checking Ollama...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 (
    echo       Already running. OK.
    goto ollama_ok
)
echo       Starting Ollama...
start "Ollama Server" /min "C:\Users\rvn92\AppData\Local\Programs\Ollama\ollama.exe" serve
set /a tries=0
:wait_ollama
timeout /t 2 /nobreak >nul 2>&1
set /a tries+=1
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 goto ollama_ok
if %tries% geq 15 goto ollama_fail
goto wait_ollama
:ollama_fail
echo       FAILED: Ollama did not respond after 30 seconds.
echo       Try running ollama.exe serve manually to see the error.
pause
exit /b 1
:ollama_ok
echo       Ollama started. OK.
echo.

:: ── 2. ComfyUI ────────────────────────────────────────────────────────────────
echo [2/3] Checking ComfyUI...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 (
    echo       Already running. OK.
    goto comfy_ok
)
echo       Starting ComfyUI on port 8188...
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\rvn92\Documents\mtg_deck_builder\launch_comfyui.ps1"
if %errorlevel% neq 0 (
    echo       FAILED: launch_comfyui.ps1 returned an error. Check the path config in that file.
    pause
    exit /b 1
)
echo       Waiting for ComfyUI to initialize (up to 90s)...
set /a tries=0
:wait_comfy
timeout /t 3 /nobreak >nul 2>&1
set /a tries+=1
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 goto comfy_ok
if %tries% geq 30 goto comfy_fail
goto wait_comfy
:comfy_fail
echo       FAILED: ComfyUI did not respond after 90 seconds.
echo       Check the minimized ComfyUI window for the startup error.
pause
exit /b 1
:comfy_ok
echo       ComfyUI started. OK.
echo.

:: ── 3. FastAPI / Uvicorn ──────────────────────────────────────────────────────
echo [3/3] Starting FastAPI backend...

:: Kill anything currently holding port 8000
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%p >nul 2>&1
)
timeout /t 2 /nobreak >nul 2>&1

start "MTG Deck Builder API" /min cmd /c "cd /d C:\Users\rvn92\Documents\mtg_deck_builder && set PYTHONIOENCODING=utf-8 && C:\Python314\python.exe server.py >> server.log 2>&1"
echo       Waiting for FastAPI to come up (up to 30s)...
set /a tries=0
:wait_api
timeout /t 2 /nobreak >nul 2>&1
set /a tries+=1
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/playstyles' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 goto api_ok
if %tries% geq 15 goto api_fail
goto wait_api
:api_fail
echo       FAILED: FastAPI did not respond after 30 seconds.
echo       Check server.log for the startup error.
pause
exit /b 1
:api_ok
echo       FastAPI started. OK.
echo.

:: ── Done ──────────────────────────────────────────────────────────────────────
echo ============================================
echo  All services running!
echo ============================================
echo.
echo   App:      http://localhost:8000
echo   ComfyUI:  http://localhost:8188
echo   Ollama:   http://localhost:11434
echo.
timeout /t 2 /nobreak >nul 2>&1
start "" "http://localhost:8000"
echo Press any key to close this window (services keep running in background).
pause >nul
