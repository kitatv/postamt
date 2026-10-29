$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -m venv .venv
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            & python -m venv .venv
        } else {
            throw 'Python 3.12 oder neuer installieren (python.org), dann erneut ausfuehren.'
        }
        if ($LASTEXITCODE -ne 0) { throw 'Virtuelle Umgebung konnte nicht erstellt werden.' }
    }
    $Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    & $Python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 oder neuer erforderlich.' }
    & $Python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Installation der Abhaengigkeiten fehlgeschlagen.' }
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Abhaengigkeiten sind inkonsistent. Installation pruefen.' }
    & $Python -c 'import vobject, defusedxml.ElementTree, tinycss2'
    if ($LASTEXITCODE -ne 0) { throw 'CardDAV/vCard-Abhaengigkeiten fehlen. Installation pruefen.' }
    & $Python windows\configure.py
    if ($LASTEXITCODE -ne 0) { throw 'Konfiguration fehlgeschlagen.' }
    & $Python -m flask --app postamt upgrade-db
    if ($LASTEXITCODE -ne 0) { throw 'Datenbankinitialisierung fehlgeschlagen. .env pruefen.' }
    Write-Host 'Installation abgeschlossen. Benutzer mit windows\create-user.ps1 anlegen, dann windows\start.ps1 starten.'
} finally {
    Pop-Location
}
