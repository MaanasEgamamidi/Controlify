@echo off
rem Stop Controlify for now. This DISABLES autostart, so nothing comes back on
rem its own - to get it watching again:
rem     powershell -NoProfile -Command "Enable-ScheduledTask -TaskName Controlify; Start-ScheduledTask -TaskName Controlify"
rem A killed process can't clean up after itself, so afterwards restore
rem Spotify's volume if an ad was being muted.
cd /d "%~dp0"
powershell -NoProfile -Command "Disable-ScheduledTask -TaskName 'Controlify' -ErrorAction SilentlyContinue | Out-Null; Stop-ScheduledTask -TaskName 'Controlify' -ErrorAction SilentlyContinue"
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" | Where-Object { $_.CommandLine -match 'controlify.py' } | Sort-Object { $_.CommandLine -notmatch '--watch' }; $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" controlify.py --restore
) else (
    echo No .venv found; skipped restoring Spotify's volume.
)