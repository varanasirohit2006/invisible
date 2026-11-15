[CmdletBinding()]
param([switch]$RuntimeOnly)

$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectDirectory
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Creating the Python environment failed.' }
    }
    $requirementsFile = if ($RuntimeOnly) { 'requirements.txt' } else { 'requirements-dev.txt' }
    & '.\.venv\Scripts\python.exe' -m pip install -r $requirementsFile
    if ($LASTEXITCODE -ne 0) { throw 'Installing Python dependencies failed.' }
    Push-Location -LiteralPath (Join-Path $projectDirectory 'frontend')
    try {
        npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Installing frontend dependencies failed.' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Building the dashboard failed.' }
    }
    finally { Pop-Location }
    Write-Host 'Setup complete. Run .\scripts\start.ps1 to start the local app.'
}
finally { Pop-Location }

