# Runs the digest on this PC (used by the 7:00 scheduled task).
# Reads settings from .env next to this script. Output is appended to digest.log.
Set-Location $PSScriptRoot

# If the local LLM is used, make sure Ollama is running.
$envFile = Join-Path $PSScriptRoot ".env"
if ((Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^\s*LLM_PROVIDER\s*=\s*ollama' -Quiet)) {
    try { Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 5 | Out-Null }
    catch {
        Start-Process ollama -ArgumentList serve -WindowStyle Hidden
        Start-Sleep -Seconds 10
    }
}

"===== $(Get-Date -Format 'yyyy-MM-dd HH:mm') =====" | Out-File digest.log -Append -Encoding utf8
python news_digest.py *>&1 | Out-File digest.log -Append -Encoding utf8
