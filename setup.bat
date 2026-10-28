@echo off
rem One-time setup: create .venv and install the runtime dependencies.
rem   setup.bat          runtime only
rem   setup.bat --dev    also install the test dependencies
setlocal
cd /d "%~dp0"

echo == Controlify setup ==

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python 3 was not found on PATH.
    echo Install it from https://www.python.org/downloads/ and tick
    echo "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 (
    echo Python 3.9 or newer is required.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
) else (
    echo .venv already exists.
)

echo Installing dependencies ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

if /i "%~1"=="--dev" (
    echo Installing test dependencies ...
    ".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
    if errorlevel 1 goto :fail
)

echo.
echo Done. Next:
echo   run.bat                  run with a visible console
echo   run-hidden.vbs           run in the background
echo   settings.bat             open the settings window
echo   install-autostart.ps1    start automatically at logon
echo.
echo While Controlify runs, a tray icon opens the same settings.
echo.
pause
exit /b 0

:fail
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
