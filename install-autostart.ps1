# Start Controlify at logon and keep it alive. Run once from PowerShell:
#   .\install-autostart.ps1
# Remove later with:  .\install-autostart.ps1 -Remove
#
# Why a scheduled task instead of a Startup-folder shortcut: the shortcut only
# ever runs once, at logon, and nothing brings Controlify back if it dies later.
# The task runs the keeper (--keep-alive), which supervises the watcher and
# stays "running" for as long as you are logged in; Task Scheduler restarts it
# if it ever exits.
param([switch]$Remove)

$TaskName = 'Controlify'
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Controlify.lnk'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $lnk -ErrorAction SilentlyContinue
    "Removed autostart (task + shortcut)."
    return
}

$pyw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pyw)) { throw "missing $pyw - run setup.bat first" }

$action = New-ScheduledTaskAction -Execute $pyw `
    -Argument "`"$PSScriptRoot\controlify.py`" --keep-alive" -WorkingDirectory $PSScriptRoot
$triggers = @(
    New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    # Backstop: if the keeper itself is killed, Task Scheduler's own
    # restart-on-failure does NOT fire (a killed process has no exit code), so
    # re-check periodically. MultipleInstances=IgnoreNew makes this a no-op
    # while the keeper is already up.
    New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(15) `
        -RepetitionInterval (New-TimeSpan -Minutes 15)
)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)   # never time out, however long you stay logged in
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
    -Settings $settings -Principal $principal `
    -Description 'Mutes Spotify ads and pauses Spotify while Wispr Flow dictates.' `
    -Force | Out-Null

# The old Startup shortcut would launch a second watcher; the mutex would block
# it, but there is no reason to keep it around.
Remove-Item $lnk -ErrorAction SilentlyContinue

Enable-ScheduledTask -TaskName $TaskName | Out-Null
Start-ScheduledTask -TaskName $TaskName
"Installed autostart: task '$TaskName' starts at logon and restarts if it dies."
"Start it now with:  Start-ScheduledTask -TaskName $TaskName"
"Stop it with:      .\stop.bat      (this also disables autostart)"
"Re-enable with:    powershell -NoProfile -Command ""Enable-ScheduledTask -TaskName $TaskName; Start-ScheduledTask -TaskName $TaskName"""