@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo L'environnement n'existe pas encore. Lance d'abord build_windows.bat.
    pause
    exit /b 1
)
.venv\Scripts\python.exe main.py
