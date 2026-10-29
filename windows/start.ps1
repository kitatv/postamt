param(
    [string]$BindAddress = '127.0.0.1',
    [ValidateRange(1, 65535)][int]$Port = 5000
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Zuerst windows\setup.ps1 ausfuehren.' }
& $Python (Join-Path $PSScriptRoot 'serve.py') --host $BindAddress --port $Port
if ($LASTEXITCODE -ne 0) { throw 'Postamt wurde mit einem Fehler beendet.' }
