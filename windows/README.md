# Postamt unter Windows

Voraussetzungen: Windows 10/11 oder Windows Server, Python **3.12 oder neuer** von python.org und Internetzugriff fuer die Paketinstallation. Python inklusive Python-Launcher installieren. Kein Docker und kein MySQL-Server fuer die voreingestellte SQLite-Variante erforderlich. Das Projekt ist eine Webanwendung; es wird im Browser bedient.

## Installation

ZIP in einen beschreibbaren Ordner entpacken, z. B. `C:\Apps\Postamt`. In PowerShell in diesen Projektordner wechseln (dort liegt `requirements.txt`):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\create-user.ps1 -Email "admin@example.de" -Name "Administration"
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\start.ps1
```

Die ExecutionPolicy-Option gilt nur fuer den jeweiligen Prozess; sie aendert keine systemweite Richtlinie. Falls die Organisation die Skriptausfuehrung verbindlich sperrt, die untenstehenden Python-Befehle verwenden oder die IT kontaktieren. Administratorrechte sind bei einer vorhandenen Python-Installation nicht erforderlich.

Das Benutzerpasswort wird verdeckt abgefragt (mindestens 12 Zeichen). Anschliessend im Browser **http://127.0.0.1:5000** oeffnen. Mit `Strg+C` den Server beenden. Fuer weitere Benutzer `create-user.ps1` erneut aufrufen. Unter **Konten** IMAP-/POP3- und SMTP-Zugangsdaten hinterlegen.

Das Setup erstellt `.venv`, installiert die Abhaengigkeiten und legt nur bei fehlender `.env` eine SQLite-Konfiguration mit zufaelligen Schluesseln an. Eine vorhandene `.env` und vorhandene Daten bleiben erhalten. Dieselben Schritte koennen erneut ausgefuehrt werden. Eine aus Linux kopierte `.venv` vor dem Windows-Setup entfernen; virtuelle Umgebungen sind nicht portabel. Das Download-ZIP enthaelt keine `.venv`.

## Datenbank und Konfiguration

Standard: `DATABASE_URL=sqlite:///postamt.db`. Die Datenbank entsteht unter `instance\postamt.db`. Fuer einen absoluten Windows-Pfad Vorwaertsschraegstriche verwenden:

```dotenv
DATABASE_URL=sqlite:///C:/PostamtDaten/postamt.db
```

MySQL bleibt alternativ moeglich; dafuer eine eigene Datenbank anlegen und `.env` anpassen:

```dotenv
DATABASE_URL=mysql+pymysql://postamt:URL_KODIERTES_PASSWORT@127.0.0.1:3306/postamt?charset=utf8mb4
```

Danach `setup.ps1` erneut ausfuehren. Ein Datenbankwechsel uebertraegt keine vorhandenen Daten. `.env` enthaelt vertrauliche Schluessel und darf nicht weitergegeben werden. Windows-Dateiberechtigungen so setzen, dass nur berechtigte Benutzer auf Projekt, `.env` und Datenbank zugreifen koennen. Datenbank und Fernet-Schluessel sicher sichern; SQLite bei gestopptem Server sichern oder die SQLite-Backup-API verwenden.

## Start und Betrieb

`start.ps1` verwendet **Waitress**, weil Gunicorn nicht auf Windows laeuft. Standardmaessig ist der Server nur auf diesem Computer erreichbar. Ein anderer Port ist moeglich:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\start.ps1 -Port 8080
```

Fuer einen geplanten Netzwerkbetrieb kann `-BindAddress 0.0.0.0` angegeben werden. Dafuer HTTPS ueber einen Reverse-Proxy einrichten, `COOKIE_SECURE=1` in `.env` setzen und die Windows-Firewall gezielt konfigurieren. Der lokale Standard nutzt HTTP und deshalb `COOKIE_SECURE=0`. Der Startbefehl bleibt im Vordergrund; eine automatische Windows-Dienstinstallation ist nicht enthalten.

## Ohne PowerShell-Skripte

In der Eingabeaufforderung im Projektverzeichnis:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe windows\configure.py
.venv\Scripts\python.exe -m flask --app postamt init-db
.venv\Scripts\python.exe -m flask --app postamt create-user admin@example.de --name Administration
.venv\Scripts\python.exe windows\serve.py
```

Mailabruf fuer alle Konten: `.venv\Scripts\python.exe -m flask --app postamt sync-mail`. Diesen Befehl bei Bedarf ueber die Windows-Aufgabenplanung mit dem Projektordner als Arbeitsverzeichnis ausfuehren. Tests: `.venv\Scripts\python.exe -m pytest -q`.

Funktionsumfang und Grenzen der Mailanbindung stehen in der [Projekt-README](../README.md). Die Anwendung und der Waitress-Start werden in der Linux-Entwicklungsumgebung geprueft; ein nativer Windows-Test ist dort nicht moeglich.

## Aktualisieren

Vor einem Update Server und Abrufjobs stoppen und Datenbank sowie `.env` sichern. Dann `setup.ps1` erneut ausfuehren. Es aktualisiert die Abhaengigkeiten und ruft `upgrade-db` auf; bestehende Schluessel werden nicht ersetzt. Danach `start.ps1` starten. Details zu GUIDs und neuen Einstellungen stehen in der Projekt-README.

## Fehler: No module named vobject

Nach einem Projektupdate muessen auch die Abhaengigkeiten in der virtuellen Umgebung aktualisiert werden. Im Projektordner bei gestopptem Server `setup.ps1` erneut ausfuehren:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\setup.ps1
```

Alternativ nur die Python-Pakete aktualisieren:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Danach mit `windows\start.ps1` neu starten. Kein globales `pip` verwenden: Installation und Server muessen denselben Python-Interpreter nutzen. Das Setup prueft die Paketkonsistenz und den Import der CardDAV-Abhaengigkeiten. Lokale Kontakte funktionieren auch ohne installierte CardDAV-Pakete; CardDAV und vCard-Import/-Export zeigen in diesem Fall einen Installationshinweis.
