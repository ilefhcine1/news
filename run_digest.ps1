# Lance la veille sur ce PC (utilisé par la tâche planifiée de 06:15).
# Lit les réglages dans .env à côté de ce script. Le script Python écrit lui-même digest.log.
Set-Location $PSScriptRoot
$log = Join-Path $PSScriptRoot "digest.log"
function Write-Log($msg) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') RUN $msg" | Out-File $log -Append -Encoding utf8 }

# Python du venv du projet (sinon celui du PATH).
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

# S'assurer qu'Ollama tourne (démarrage puis attente jusqu'à 60 s).
function Test-Ollama { try { Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 5 | Out-Null; $true } catch { $false } }
if (-not (Test-Ollama)) {
    Write-Log "Ollama ne répond pas : démarrage de 'ollama serve'"
    Start-Process ollama -ArgumentList serve -WindowStyle Hidden
    for ($i = 0; $i -lt 12 -and -not (Test-Ollama); $i++) { Start-Sleep -Seconds 5 }
    if (-not (Test-Ollama)) { Write-Log "ERREUR : Ollama n'a pas démarré"; exit 1 }
}

Write-Log "Démarrage de la veille"
# La sortie console n'est gardée qu'en cas d'échec (erreur avant que Python n'ouvre son log).
$out = & $python news_digest.py 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Log "ERREUR : code de sortie $LASTEXITCODE"
    $out | Select-Object -Last 30 | Out-File $log -Append -Encoding utf8
}
exit $LASTEXITCODE
