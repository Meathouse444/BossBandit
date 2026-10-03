# Runs BossBandit automatically every day.
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1            (7:00 AM)
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1 -Time 05:30
# Remove it later with:  Unregister-ScheduledTask -TaskName "BossBandit Daily"
param([string]$Time = "07:00")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$bat = Join-Path $root "scripts\run_daily.bat"

$action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`"" -WorkingDirectory $root
$trigger  = New-ScheduledTaskTrigger -Daily -At $Time
# StartWhenAvailable: if the PC was off/asleep at that time, run as soon as it's back on.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask -TaskName "BossBandit Daily" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Finds and renders today's millennial streamer clips" -Force | Out-Null

Write-Host "Scheduled: BossBandit runs every day at $Time." -ForegroundColor Green
Write-Host "Your videos land in the output folder; open the newest one with:  .venv\Scripts\bossbandit open"
