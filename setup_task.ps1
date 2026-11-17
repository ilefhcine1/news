# Registers a Windows scheduled task that runs the digest every day at 07:00.
# Run once:  powershell -ExecutionPolicy Bypass -File setup_task.ps1
# Remove:    Unregister-ScheduledTask -TaskName DailyTechDigest -Confirm:$false
$script = Join-Path $PSScriptRoot "run_digest.ps1"

$action   = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
            -WorkingDirectory $PSScriptRoot
$trigger  = New-ScheduledTaskTrigger -Daily -At 7:00
# StartWhenAvailable: if the PC was off/asleep at 7:00, run as soon as it is back.
# WakeToRun: wake the PC from sleep (not from shutdown) to run it.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 45)

Register-ScheduledTask -TaskName "DailyTechDigest" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Daily AI / Tech / Cyber news digest" -Force | Out-Null
Write-Host "Scheduled task 'DailyTechDigest' created: every day at 07:00."
Write-Host "Test it now with:  Start-ScheduledTask -TaskName DailyTechDigest"
