@echo off
REM Myth Forge - Deck-Strength Data (CCM) Downloader for Windows
REM Optional - see docs/ENGINE_DATA.md. Without this the engine still runs, on
REM Oracle-text heuristics instead of compiled card semantics.

cd /d "%~dp0"

echo.
echo ====================================
echo  MYTH FORGE CCM DOWNLOADER
echo ====================================
echo.

python download-ccm.py %*

pause
