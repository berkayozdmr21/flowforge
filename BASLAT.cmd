@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto existing
where py >nul 2>nul
if not errorlevel 1 goto pylauncher
if exist "%UserProfile%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" goto bundled
python scripts\setup.py
goto finished
:pylauncher
py -3 scripts\setup.py
goto finished
:bundled
"%UserProfile%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\setup.py
goto finished
:existing
".venv\Scripts\python.exe" scripts\setup.py
:finished
if errorlevel 1 pause
