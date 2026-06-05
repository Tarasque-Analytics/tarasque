# ============================================================================
#  register_daily_task.ps1 — register Tarasque nightly + weekly refresh tasks
# ============================================================================
#  Run this ONCE (as Administrator) to install the scheduled tasks:
#
#    Right-click PowerShell → "Run as Administrator"
#    cd C:\Users\Leo DiPietro\Desktop\volarbmodel
#    .\scripts\register_daily_task.ps1
#
#  After registration:
#    - Tarasque nightly refresh runs DAILY at 5:30 PM ET (Mon-Fri)
#    - Tarasque weekly extend runs SUNDAY at 2:00 AM ET
#    - Both run whether or not the user is logged in
#    - Logs land in logs\daily_YYYY-MM-DD.log and logs\weekly_extend_YYYY-MM-DD.log
#
#  To verify:    Get-ScheduledTask -TaskName "Tarasque*"
#  To unregister: Unregister-ScheduledTask -TaskName "Tarasque*" -Confirm:$false
#  To run now:    Start-ScheduledTask -TaskName "Tarasque Nightly Refresh"
# ============================================================================

$ErrorActionPreference = 'Stop'

# Resolve absolute paths
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$DailyBat = Join-Path $RepoRoot 'scripts\daily_refresh.bat'
$WeeklyBat = Join-Path $RepoRoot 'scripts\weekly_extend.bat'

if (-not (Test-Path $DailyBat)) {
    Write-Error "daily_refresh.bat not found at $DailyBat"
    exit 1
}
if (-not (Test-Path $WeeklyBat)) {
    Write-Error "weekly_extend.bat not found at $WeeklyBat"
    exit 1
}

Write-Host "Registering Tarasque scheduled tasks..."
Write-Host "  Repo root: $RepoRoot"
Write-Host "  Daily:  $DailyBat"
Write-Host "  Weekly: $WeeklyBat"
Write-Host ""

# ── Nightly refresh (daily Mon-Fri at 5:30 PM) ──────────────────────────────
$DailyAction = New-ScheduledTaskAction -Execute $DailyBat -WorkingDirectory $RepoRoot
$DailyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 5:30PM
$DailySettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$DailyPrincipal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

Register-ScheduledTask `
    -TaskName "Tarasque Nightly Refresh" `
    -Description "Refreshes data, runs daily forecast, computes SHAP, exports webapp bundle" `
    -Action $DailyAction `
    -Trigger $DailyTrigger `
    -Settings $DailySettings `
    -Principal $DailyPrincipal `
    -Force | Out-Null

Write-Host "[OK] Registered: Tarasque Nightly Refresh (Mon-Fri 5:30 PM)"

# ── Weekly extend (Sunday 2:00 AM) ──────────────────────────────────────────
$WeeklyAction = New-ScheduledTaskAction -Execute $WeeklyBat -WorkingDirectory $RepoRoot
$WeeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 2:00AM
$WeeklySettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask `
    -TaskName "Tarasque Weekly Extend" `
    -Description "Weekly WFA retrain + prediction extension to TODAY for all 93 tickers" `
    -Action $WeeklyAction `
    -Trigger $WeeklyTrigger `
    -Settings $WeeklySettings `
    -Principal $DailyPrincipal `
    -Force | Out-Null

Write-Host "[OK] Registered: Tarasque Weekly Extend (Sunday 2:00 AM)"
Write-Host ""
Write-Host "Both tasks registered. Verify with:"
Write-Host "  Get-ScheduledTask -TaskName 'Tarasque*'"
Write-Host ""
Write-Host "To run the daily refresh manually right now (smoke test):"
Write-Host "  Start-ScheduledTask -TaskName 'Tarasque Nightly Refresh'"
