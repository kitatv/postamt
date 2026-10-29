param(
    [Parameter(Mandatory = $true)][string]$Email,
    [Parameter(Mandatory = $true)][string]$Name
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Zuerst windows\setup.ps1 ausfuehren.' }
Push-Location $ProjectRoot
try {
    & $Python -m flask --app postamt create-user $Email --name $Name
    if ($LASTEXITCODE -ne 0) { throw 'Benutzer konnte nicht angelegt werden.' }
} finally {
    Pop-Location
}
