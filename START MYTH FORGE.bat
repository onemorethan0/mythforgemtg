@echo off
REM ============================================================
REM   START MYTH FORGE  --  the one-click launcher
REM ============================================================
REM Double-click this file to start everything the app needs:
REM   llama-swap   :8010  (deck theming LLM)      auto-started
REM   strength API :8020  (MythGauntlet analysis) auto-started
REM   Myth Forge   :8000  (the web app)           this window
REM ComfyUI (:8188, card art) is optional -- start it from
REM manage.bat option 3 when you want image generation.
REM
REM When the log says the server is running, open:
REM     http://localhost:8000
REM Keep this window open; press Ctrl+C to stop.
REM ============================================================
cd /d "%~dp0"
call manage.bat start
