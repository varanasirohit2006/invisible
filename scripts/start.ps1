[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [switch]$Demo,
    [switch]$NoAgent
)

$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectDirectory
try {
    if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
        throw 'Build the dashboard first with .\scripts\setup.ps1 or npm run build in frontend.'
    }
    $pythonExecutable = if (Test-Path -LiteralPath '.venv\Scripts\python.exe') { '.\.venv\Scripts\python.exe' } else { 'python' }
    $launcherArguments = @('run.py', '--port', [string]$Port, '--show-token')
    if ($Demo) { $launcherArguments += '--demo' }
    if ($NoAgent) { $launcherArguments += '--no-agent' }
    # The launcher returns successfully when this app is already on the port.
    & $pythonExecutable @launcherArguments
    if ($LASTEXITCODE -ne 0) { throw 'The local app could not start. See the message above; use -Port to choose another port if needed.' }
}
finally { Pop-Location }

