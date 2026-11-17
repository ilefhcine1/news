# Crée la tâche planifiée Windows qui lance la veille chaque jour à 06:15.
# À lancer une fois :  powershell -ExecutionPolicy Bypass -File setup_task.ps1
# Supprimer :          Unregister-ScheduledTask -TaskName DailyTechDigest -Confirm:$false
$script = Join-Path $PSScriptRoot "run_digest.ps1"

$action   = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
            -WorkingDirectory $PSScriptRoot
$trigger  = New-ScheduledTaskTrigger -Daily -At 6:15
# WakeToRun          : sort le PC de la veille (pas d'un arrêt complet) pour lancer la tâche.
# StartWhenAvailable : si 06:15 a été manqué (PC éteint), lance la tâche dès que possible.
# AllowStartIfOnBatteries / DontStopIfGoingOnBatteries : fonctionne aussi sur batterie.
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
            -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "DailyTechDigest" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Veille quotidienne IA / Tech / Cyber (Ollama local)" -Force | Out-Null
Write-Host "Tâche planifiée 'DailyTechDigest' créée : tous les jours à 06:15."
Write-Host "Test immédiat :  Start-ScheduledTask -TaskName DailyTechDigest"
