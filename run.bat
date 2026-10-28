@echo off
rem Run Controlify with a visible console (Ctrl+C to stop).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo No .venv found. Run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" controlify.py %*
