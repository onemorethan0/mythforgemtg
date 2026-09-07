@echo off
REM Quick start - Development server
REM Actually delegates to manage.bat start (was a bare `python server.py` that skipped
REM the llama-swap/strength-engine ensure steps despite this comment always claiming
REM otherwise - that gap produced unthemed decks and "bracket unavailable" for anyone
REM who used this instead of the menu. See CLAUDE.md.
call "%~dp0manage.bat" start
