@echo off
REM Myth Forge Model Downloader for Windows

cd /d "%~dp0"

echo.
echo ====================================
echo  MYTH FORGE MODEL DOWNLOADER
echo ====================================
echo.

python download-models.py

pause
