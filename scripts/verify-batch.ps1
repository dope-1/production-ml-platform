$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Existing Python 3.12 .venv required. See README." }
function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Program $Arguments" }
}
Invoke-Checked -Program $python -Arguments @("-m", "pip", "install", "-r", "requirements-dev.lock")
Invoke-Checked -Program $python -Arguments @("-m", "pip", "install", "--no-deps", "-e", ".")
Invoke-Checked -Program "docker" -Arguments @("compose", "config", "--quiet")
Invoke-Checked -Program "docker" -Arguments @("compose", "up", "--build", "--detach", "--wait", "--wait-timeout", "300")
Invoke-Checked -Program $python -Arguments @("scripts/verify_batch.py")
