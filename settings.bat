@echo off
rem Open the Controlify settings window. This works even when Spotify is
rem closed; while Controlify is running, the same window is on the tray icon.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo No .venv found. Run setup.bat first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" controlify.py --settings
