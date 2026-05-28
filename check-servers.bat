@echo off
REM Check status of ComfyUI and Myth Forge servers

echo.
echo ============================================
echo  MYTH FORGE - Server Status Check
echo ============================================
echo.

echo Checking for running servers...
echo.

REM Check ComfyUI on port 8188
echo [*] ComfyUI (port 8188):
netstat -aon 2>nul | find ":8188" | find "LISTENING" >nul
if %errorlevel% equ 0 (
  for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":8188" ^| find "LISTENING"') do (
    echo    ✓ RUNNING (PID: %%a)
  )
) else (
  echo    ✗ NOT RUNNING
)

echo.

REM Check Myth Forge on port 8000
echo [*] Myth Forge (port 8000):
netstat -aon 2>nul | find ":8000" | find "LISTENING" >nul
if %errorlevel% equ 0 (
  for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":8000" ^| find "LISTENING"') do (
    echo    ✓ RUNNING (PID: %%a)
  )
) else (
  echo    ✗ NOT RUNNING
)

echo.

REM Check Ollama on port 11434
echo [*] Ollama (port 11434):
netstat -aon 2>nul | find ":11434" | find "LISTENING" >nul
if %errorlevel% equ 0 (
  for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":11434" ^| find "LISTENING"') do (
    echo    ✓ RUNNING (PID: %%a)
  )
) else (
  echo    ✗ NOT RUNNING
)

echo.

REM Check for orphaned Python processes
echo [*] Orphaned Python processes:
tasklist 2>nul | find /i "python" >nul
if %errorlevel% equ 0 (
  echo    Found:
  tasklist 2>nul | find /i "python"
) else (
  echo    ✓ None found
)

echo.
echo ============================================
echo.
echo Quick commands:
echo   kill-servers.bat     - Kill Myth Forge process
echo   start-clean.bat      - Start Myth Forge fresh
echo   check-servers.bat    - This status check
echo.
pause
