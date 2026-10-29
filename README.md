# Postamt

Mehrbenutzerfähiger E-Mail-Client mit Flask, wahlweise MySQL 8.4 oder SQLite und einer responsiven deutschsprachigen Oberfläche.

## Funktionsumfang

- Anmeldung mit gehashten Passwörtern; Benutzer werden administrativ per CLI angelegt.
- Mehrere persönliche IMAP- und POP3-Konten; TLS mit Zertifikatsprüfung, verschlüsselte Kontopasswörter (Fernet).
- Empfang, MIME-Verarbeitung, HTML-Ansicht ohne externe Tracker oder ausführbare Inhalte, Anhänge zum Download.
- Rich-Text-Editor mit Formatierung und Anhängen, Versand über SMTP mit implizitem TLS.
- Nachrichten, MIME-Originale, Anhänge, Konten, Benutzer, Ordner und Berechtigungen in der gewählten Datenbank (MySQL oder SQLite); Anhänge werden nicht als separate Dateien abgelegt.
- Lokale verschachtelte Ordner; explizite Leserechte oder Lese-/Schreibrechte pro Benutzer und Ordner, inklusive Entzug.
- Suche im gewählten Ordner, Markierungen, Gelesen-Status, Verschieben und Pagination.
- CSRF-Schutz, sichere Session-Cookies als Standard, serverseitige Berechtigungsprüfung auch für HTML-Ansichten und Downloads.

## Windows

Fuer Windows stehen eine [Installationsanleitung und PowerShell-Skripte](windows/README.md) bereit. Sie richten standardmaessig SQLite ein und starten die Anwendung mit Waitress.

## Lokal starten

Python 3.12+ wird benötigt. Als Datenbank stehen MySQL 8.4 oder das in Python integrierte SQLite zur Auswahl. Im vorhandenen Checkout arbeiten; kein zusätzlicher Worktree erforderlich.

```sh
cd /workspace/postamt
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

In `.env` `DATABASE_URL`, `SECRET_KEY` und `MAIL_ENCRYPTION_KEY` eintragen; für MySQL zusätzlich unabhängige zufällige Datenbankpasswörter setzen. `.env` nicht committen. Schlüssel lokal erzeugen:

```sh
python -c 'import secrets; print(secrets.token_urlsafe(48))'
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

### SQLite

Für einen Betrieb ohne separaten Datenbankserver in `.env` setzen:

```dotenv
DATABASE_URL=sqlite:///postamt.db
```

Die Datei liegt bei dieser relativen URL unter `instance/postamt.db` im Checkout. Alternativ einen absoluten Pfad mit vier Schrägstrichen verwenden, z. B. `sqlite:////srv/postamt/postamt.db`. Das übergeordnete Verzeichnis wird bei Bedarf angelegt und muss für den Anwendungsprozess schreibbar sein. Es sind keine zusätzlichen Treiber oder MySQL-Zugangsdaten notwendig; Docker entfällt. Die Datei wird durch `init-db` angelegt. Nachrichten, Anhänge und Berechtigungen bleiben in derselben Datenbankdatei erhalten.

SQLite-Fremdschlüssel werden für jede Verbindung aktiviert. Bei konkurrierenden Schreibzugriffen wartet die Verbindung bis zu 30 Sekunden auf eine freie Datenbank. SQLite eignet sich für kleinere Installationen; für viele gleichzeitige Schreibzugriffe empfiehlt sich MySQL. `sqlite://` ist nur eine flüchtige In-Memory-Datenbank für Tests.

### MySQL

Optional startet die mitgelieferte Compose-Datei eine lokale MySQL-Datenbank mit persistentem Volume:

```sh
docker compose up -d --wait db
```

`DATABASE_URL` muss zu den gewählten MySQL-Zugangsdaten passen, z. B. `mysql+pymysql://postamt:PASSWORT@127.0.0.1:3306/postamt?charset=utf8mb4`. Sonderzeichen im Passwort URL-kodieren. Bei einer vorhandenen MySQL-Instanz eine Datenbank mit `utf8mb4` und einen eigenen Datenbankbenutzer mit Rechten auf diese Datenbank anlegen.

### Schema und Benutzer anlegen (beide Datenbanken)

```sh
flask --app postamt init-db
flask --app postamt create-user admin@example.de --name Administration
flask --app postamt run --host 0.0.0.0 --port 5000
```

Das Passwort wird interaktiv abgefragt (mindestens 12 Zeichen). Weitere Benutzer mit demselben Befehl anlegen. Flask lädt `.env` automatisch. `COOKIE_SECURE=0` nur bei lokaler HTTP-Entwicklung verwenden. Nach der Anmeldung unter **Konten** das erste Postfach verbinden und **Abrufen** ausführen. Standardports: IMAP 993, POP3 995, SMTP 465. SMTP nutzt dieselben Zugangsdaten wie der Empfang.

Die Auswahl erfolgt ausschließlich über `DATABASE_URL`; MySQL bleibt in `.env.example` voreingestellt. Ein Wechsel der URL kopiert keine bestehenden Daten. Bei einem Wechsel zwischen MySQL und SQLite müssen vorhandene Daten separat übertragen werden; `init-db` legt nur das Schema an und ist kein Migrationswerkzeug.

## Ordnerrechte

Ein Ordner ist zunächst nur für seinen Eigentümer zugänglich. Unter **Ordnerzugriff verwalten** einen vorhandenen Benutzer über seine E-Mail-Adresse freigeben. Lesen erlaubt Nachrichtenansicht und Downloads; Schreiben erlaubt zusätzlich Markierungen, Gelesen-Status und Verschieben. Zum Verschieben ist Schreibzugriff auf Quell- und Zielordner erforderlich. Nur der Eigentümer verwaltet Freigaben. Rechte werden bewusst nicht an Unterordner vererbt; jeder Unterordner wird separat freigegeben. Kontozugangsdaten und Synchronisierung bleiben ausschließlich beim Kontoeigentümer.

## Synchronisierung und Versand

Manueller Abruf erfolgt über die Kontoverwaltung. Ein externer Scheduler kann regelmäßig aus dem Checkout ausführen:

```sh
.venv/bin/flask --app postamt sync-mail
```

IMAP importiert zunächst ausschließlich INBOX. POP3 verwendet UIDL; IMAP verwendet UID und UIDVALIDITY zur Duplikatvermeidung. Auf dem Server wird nichts gelöscht und keine Nachricht als gelesen markiert. Lokale Ordner, Verschiebungen und Lesestatus werden nicht auf den Mailserver zurückgeschrieben. Beim Wechsel der IMAP-UIDVALIDITY können Nachrichten erneut importiert werden. Pro Konto nur einen Abruf gleichzeitig ausführen. Der Abruf ist synchron; für sehr große Konten den CLI-Job verwenden.

Nachrichten einschließlich MIME-Kodierung sind auf 16 MB begrenzt; größere Nachrichten führen zu einem fehlgeschlagenen Abruf. Das HTTP-Uploadlimit beträgt 25 MB, das endgültige Versandlimit ebenfalls 16 MB. Externe Bilder und HTML-Stile werden bewusst nicht geladen. OAuth2, STARTTLS, Entwürfe mit dauerhafter Speicherung, vollständige IMAP-Ordnersynchronisation und ein eingebauter Scheduler sind noch nicht implementiert. Aktuell werden Konten einmalig angelegt; Änderungen an Konten und Passwortwechsel benötigen eine spätere Verwaltungsfunktion.

SMTP und Datenbank können keine gemeinsame Transaktion bilden: Nach einem Versandfehler nicht blind erneut senden, sondern zuerst beim Anbieter den Versand prüfen. Die Oberfläche weist bei Fehlern darauf hin und behält Empfänger, Betreff und Text; Anhänge müssen erneut ausgewählt werden.

## Tests

```sh
.venv/bin/python -m pytest -q
```

Standardmäßig läuft die gesamte Anwendungstestsuite zweimal: mit SQLite im Arbeitsspeicher und mit einer temporären SQLite-Datei. Zusätzliche Tests prüfen Fremdschlüssel, Verbindungseinstellungen sowie Datenpersistenz nach einem Neustart der Anwendung. Für Integrationstests gegen MySQL eine separate Datenbank **postamt_test** anlegen und `TEST_DATABASE_URL` sicher in der Prozessumgebung setzen. **Die Tests löschen und erstellen alle Tabellen dieser Testdatenbank.** Keine produktive Datenbank verwenden.

```sh
.venv/bin/python -m pytest -q
```

Die Tests prüfen Mehrbenutzer-Isolation, Freigaben und Entzug, Anhänge, Verschlüsselung, HTML-Isolation, CSRF, MIME-Verarbeitung, Import-Deduplizierung und SMTP-Ablage. Mailprotokolle werden mit Test-Doubles geprüft; echte Anbieterverbindungen benötigen Kontozugangsdaten und Netzwerkfreigaben.

## Betrieb

Für den produktiven Betrieb HTTPS über einen Reverse-Proxy verwenden und `COOKIE_SECURE=1` setzen. Anwendung z. B. mit `.venv/bin/gunicorn --workers 2 --threads 4 --timeout 120 'postamt:create_app()'` starten; die Konfiguration dafür als Prozessumgebung bereitstellen (Gunicorn lädt `.env` nicht automatisch). Anmeldung am Reverse-Proxy begrenzen. Keine öffentliche Registrierung vorhanden.

Die gewählte Datenbank und den stabilen Fernet-Schlüssel getrennt und sicher sichern: Ohne den ursprünglichen Schlüssel sind gespeicherte Mailpasswörter nicht wiederherstellbar. Bei SQLite konsistente Backups mit der SQLite-Backup-API erstellen oder die Anwendung für die Dateisicherung anhalten; eine laufend beschriebene Datei nicht einfach kopieren. Bei MySQL den Datenbankport nicht öffentlich bereitstellen. Datenbank und Anwendung nur für berechtigte Betreiber zugänglich machen. `init-db` initialisiert das Schema; spätere Schemaänderungen benötigen geplante Migrationen, es ist noch kein Upgrade-Migrationssystem vorhanden.

Es wurden weder die Cloud-Umgebung veröffentlicht noch externe E-Mails versendet. Für echte Mailkonten müssen die jeweiligen Hosts und TLS-Ports im Netzwerk der Zielumgebung erreichbar sein.
