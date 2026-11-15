[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectDirectory
try {
    $pythonExecutable = '.\.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExecutable)) {
        throw 'Run .\scripts\setup.ps1 first.'
    }
    Push-Location -LiteralPath (Join-Path $projectDirectory 'frontend')
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Building the dashboard failed.' }
    }
    finally { Pop-Location }
    & $pythonExecutable -m pip install -r requirements-packaging.txt
    if ($LASTEXITCODE -ne 0) { throw 'Installing the packaging dependency failed.' }
    & $pythonExecutable -m PyInstaller --noconfirm --onedir --name InvisibleWorkDetector --add-data 'frontend/dist;frontend/dist' --collect-all pdfplumber --collect-all pdfminer run.py
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
    Write-Host 'Portable application: dist\InvisibleWorkDetector\InvisibleWorkDetector.exe'
    Write-Host 'Copy the complete directory. No startup registration or monitoring is enabled automatically.'
}
finally { Pop-Location }

