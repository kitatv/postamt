# Postamt

Mehrbenutzerfähiger E-Mail-Client mit Flask, wahlweise MySQL 8.4 oder SQLite und einer responsiven deutschsprachigen Oberfläche.

## Funktionsumfang

- Anmeldung mit gehashten Passwörtern; Benutzer werden administrativ per CLI angelegt.
- Mehrere persönliche IMAP- und POP3-Konten; TLS mit Zertifikatsprüfung, verschlüsselte Kontopasswörter (Fernet).
- Empfang, MIME-Verarbeitung, HTML-Ansicht ohne externe Tracker oder ausführbare Inhalte, Anhänge zum Download.
- Rich-Text-Editor mit Formatierung und Anhängen, Versand über SMTP mit implizitem TLS.
- Nachrichten, MIME-Originale, Anhänge, Konten, Benutzer, Ordner und Berechtigungen in der gewählten Datenbank (MySQL oder SQLite); Anhänge werden nicht als separate Dateien abgelegt.
- Lokale verschachtelte Ordner; explizite Leserechte oder Lese-/Schreibrechte pro Benutzer und Ordner, inklusive Entzug.
- Suche im gewählten Ordner, Markierungen, Gelesen-Status, Verschieben und schrittweises Nachladen.
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

Ein Ordner ist zunächst nur für seinen Eigentümer zugänglich. Unter **Ordnerzugriff verwalten** einen vorhandenen Benutzer über seine E-Mail-Adresse freigeben. Lesen erlaubt Nachrichtenansicht und Downloads; Schreiben erlaubt zusätzlich Markierungen und Verschieben. Beim Öffnen wird eine Nachricht automatisch als gelesen markiert; auch Benutzer mit Leserecht können sie über das Nachrichtenmenü wieder als ungelesen markieren. Der Gelesen-Status gilt gemeinsam für die Nachricht. Zum Verschieben ist Schreibzugriff auf Quell- und Zielordner erforderlich. Nur der Eigentümer verwaltet Freigaben. Rechte werden bewusst nicht an Unterordner vererbt; jeder Unterordner wird separat freigegeben. Kontozugangsdaten und Synchronisierung bleiben ausschließlich beim Kontoeigentümer.

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

Die gewählte Datenbank und den stabilen Fernet-Schlüssel getrennt und sicher sichern: Ohne den ursprünglichen Schlüssel sind gespeicherte Mailpasswörter nicht wiederherstellbar. Bei SQLite konsistente Backups mit der SQLite-Backup-API erstellen oder die Anwendung für die Dateisicherung anhalten; eine laufend beschriebene Datei nicht einfach kopieren. Bei MySQL den Datenbankport nicht öffentlich bereitstellen. Datenbank und Anwendung nur für berechtigte Betreiber zugänglich machen. `init-db` initialisiert das Schema; spätere Schemaänderungen benötigen geplante Migrationen, für die neuen Einstellungen, Konto-Ordnerzuordnungen und Nachrichten-GUIDs steht der unten beschriebene additive Upgrade-Befehl bereit.

Es wurden weder die Cloud-Umgebung veröffentlicht noch externe E-Mails versendet. Für echte Mailkonten müssen die jeweiligen Hosts und TLS-Ports im Netzwerk der Zielumgebung erreichbar sein.


## Einstellungen, Kontobäume und Leseansicht

Unter **Einstellungen** wählt jeder Benutzer sein Abrufintervall (0 = aus, sonst 30–86400 Sekunden) und die Anzahl E-Mails pro Ladeschritt (1–200, Standard 40). Der automatische Abruf läuft nur bei geöffneter Mailansicht im Browser und betrifft die eigenen Konten. Es ist kein Hintergrunddienst bei geschlossenem Browser. Der Abrufbutton neben jedem eigenen Konto erlaubt einen sofortigen Abruf.

Ordner werden als Baum unter ihrem Konto dargestellt. Neue Hauptordner können einem Konto zugeordnet werden; Unterordner übernehmen die Kontozuordnung ihres Elternordners. Lokale Ordner ohne Konto und freigegebene Ordner ohne eigenes Konto stehen in einer separaten Gruppe. Fremde Kontozugangsdaten und Kontonamen werden durch eine Ordnerfreigabe nicht offengelegt. Die IMAP-Anbindung importiert weiterhin INBOX; der Baum zeigt die lokale Ablage, keine vollständige Synchronisation aller Serverordner.

Über der Liste steht die Anzahl angezeigter Nachrichten und die Gesamtzahl der aktuellen Auswahl. **Weiter** hängt den nächsten eingestellten Block an; Suche und Markiert-Filter bleiben erhalten. Ohne JavaScript lädt der Link die entsprechend längere Liste neu. Jede Nachricht besitzt zusätzlich zur internen ID eine eindeutige UUID/GUID, die beim Verschieben erhalten bleibt.

Beim Öffnen wird die Nachricht als gelesen gespeichert. **Nachrichtenmenü → Als ungelesen markieren** setzt den Status zurück und schließt die Nachricht, damit sie nicht sofort wieder als gelesen gilt. Unbekannte Absender öffnen zunächst als Text (bei reinen HTML-Mails wird Text abgeleitet). **Als HTML anzeigen** aktiviert für diese Nachrichten eine bereinigte, isolierte HTML-Ansicht ohne externe Ressourcen. Für gemeinsam vertraute Absender gilt die unten beschriebene HTML-Freigabe.

## Bestehende Installation aktualisieren

Server und automatische Abrufjobs stoppen und Datenbank sowie `.env` sichern. Mit derselben Datenbankkonfiguration anschließend ausführen:

```sh
.venv/bin/python -m flask --app postamt upgrade-db
```

Windows:

```powershell
.venv\Scripts\python.exe -m flask --app postamt upgrade-db
```

Der Befehl ergänzt die GUID-Spalte und einen eindeutigen Index, weist bestehenden Nachrichten jeweils eine neue UUID zu und legt die Tabellen für Benutzereinstellungen und Konto-Ordnerzuordnungen an. Bestehende Posteingangs- und Gesendet-Ordner samt Unterordnern werden dem Konto zugeordnet. Der Befehl kann erneut ausgeführt werden; vorhandene GUIDs und Einstellungen bleiben erhalten. Neue Installationen verwenden weiterhin `init-db`; das Windows-Setup verwendet `upgrade-db` für Neuinstallation und Aktualisierung. Erst nach erfolgreichem Upgrade den Server wieder starten. MySQL-DDL kann nicht vollständig zurückgerollt werden; das Upgrade bei einem Fehler nach Diagnose erneut ausführen oder die Sicherung wiederherstellen.


## Vertrauen, Kontakte und Antworten

Alle Nachrichten besitzen einen **gemeinsamen Vertrauensstatus** (`Message.trusted`). **Absender vertrauen** gibt die normalisierte From-Adresse für alle Benutzer frei; eine Namensgleichheit allein genügt nicht. Auch ein Kontakt im gemeinsamen Adressbuch macht die zugehörige E-Mail-Adresse für alle vertraut. Der Status wird beim Anzeigen sowie bei Kontakt- und Vertrauensänderungen aktualisiert und bei neuen Importen übernommen. Vertrauen ist eine gemeinsame Freigabe der Adresse, keine kryptografische Prüfung des Absenders. Ordnerberechtigungen bleiben davon unabhängig.

**Kontakt anlegen** öffnet einen Dialog mit vorbelegter Absenderadresse und Pflichtfeld Name. Die Adresse wird serverseitig aus der Nachricht übernommen. Nach dem Speichern erscheint `Kontaktname (adresse@example.de)` über der Nachricht. Das lokale Adressbuch ist über **Adressbuch** erreichbar und unterstützt vCard-Import/-Export.

Vertraute Nachrichten öffnen automatisch in HTML. Externe Bilder und verlinkte Stylesheets sowie bereinigte Inline-Formatierung dürfen dann geladen werden; dabei kann der externe Anbieter den Abruf sehen. Die Darstellung bleibt in einem Sandbox-Iframe. JavaScript, Formulare und eingebettete aktive Inhalte sind weiterhin gesperrt. Über **Als Text anzeigen** lässt sich auch eine vertraute Nachricht als Text lesen. Unbekannte Nachrichten laden keine externen Inhalte.

Die Nachrichtenaktionen stehen als Buttons über der Vorschau. **Antworten** und **Weiterleiten** sind nur bei vertrauten Nachrichten, Schreibrecht auf den Quellordner und einem eigenen Versandkonto verfügbar; dies wird auch bei direkten HTTP-Anfragen geprüft. Der Editor belegt Empfänger (Antwort), Betreff und zitierten Originaltext vor. Bei Weiterleitungen werden die Originalanhänge zusätzlich mitgesendet. Antworten setzen `In-Reply-To` und `References`, wenn das Original eine Message-ID besitzt. Nach erfolgreichem SMTP-Versand und lokaler Ablage wird die ursprüngliche Nachricht als beantwortet bzw. weitergeleitet markiert. Die Liste zeigt **→** für weitergeleitet und **←** für beantwortet, untereinander und bei Bedarf gemeinsam. Diese Versandkennzeichen gelten gemeinsam für die Nachricht.

### CardDAV

Unter **Adressbuch** kann eine externe CardDAV-Adressbuchsammlung mit vollständiger HTTPS-URL, Benutzername und Passwort/App-Passwort verbunden werden. Zugangsdaten werden wie Mailpasswörter verschlüsselt. **Kontakte abrufen** importiert Kontakte per CardDAV `addressbook-query` (REPORT); die enthaltenen E-Mail-Adressen gelten danach als vertraut. Über den Nachrichtendialog kann ein neuer Kontakt wahlweise lokal oder direkt im verbundenen CardDAV-Adressbuch (vCard-PUT mit `If-None-Match`) angelegt werden.

Die Sammlung muss bereits existieren; automatische Server-/Sammlungserkennung, OAuth, ein eigener CardDAV-Server sowie die Synchronisation von Änderungen und Löschungen in beide Richtungen sind nicht enthalten. Imports aktualisieren Namen desselben Adressbuchs, überschreiben aber keine Kontakte anderer Quellen. Entfernte Kontakte werden beim Import nicht automatisch lokal gelöscht. Abruf erfolgt manuell; vCard-Import/-Export ist zusätzlich verfügbar. Der CardDAV-Host muss aus der Zielumgebung per HTTPS erreichbar sein. TLS-Prüfung bleibt aktiv, Weiterleitungen werden zum Schutz der Zugangsdaten nicht verfolgt.

Nach dem Aktualisieren der Abhängigkeiten das vorhandene `upgrade-db` bei gestopptem Server ausführen. Es ergänzt `replied`/`forwarded` für bestehende Nachrichten und die Tabellen für Kontakte, CardDAV-Bücher und gemeinsame Vertrauensfreigaben. Vorher Datenbank und `.env` sichern. Echte CardDAV-Server und Mailanbieter benötigen deine Zugangsdaten; die automatisierten Tests verwenden Protokoll-Testdoubles.


## Gemeinsames Adressbuch und ungelesene Nachrichten

Alle angemeldeten Benutzer dürfen das gemeinsame Adressbuch einsehen, Kontakte anlegen, Namen und E-Mail-Adressen bearbeiten, Kontakte löschen sowie vCards importieren und exportieren. Auch verbundene CardDAV-Adressbücher können gemeinsam für Abruf und Kontaktanlage genutzt werden; gespeicherte Passwörter werden nicht ausgegeben. Änderungen an importierten Kontakten erfolgen lokal, nicht per CardDAV-Update; ein späterer Abruf kann den Namen erneut aus der Quelle übernehmen.

Bestehende personenbezogene Kontakte und Absenderfreigaben werden nach dem Upgrade gemeinsam ausgewertet. `owner_id` dokumentiert weiterhin den Ersteller, beschränkt aber nicht mehr den Adressbuchzugriff. Doppelte Adressen aus älteren Installationen bleiben erhalten und werden als ein gemeinsamer Eintrag angezeigt (älteste Kontakt-ID). Bearbeiten und Löschen wirken auf alle bisherigen Kontakte derselben Adresse. Das Löschen eines Kontakts entfernt dessen abgeleitetes Vertrauen; eine zusätzlich explizit erteilte Absenderfreigabe bleibt bestehen. Die alte Tabelle `MessageTrust` wird aus Kompatibilitätsgründen erhalten, aber nicht mehr als Quelle des Vertrauensstatus verwendet.

Die Nachrichtenliste zeigt Spalten für Kontaktname (ersatzweise Absenderadresse) und Betreff, das Sendedatum einschließlich Uhrzeit in UTC sowie Statussymbole für gelesen/ungelesen, Vertrauen, Markierung, Anhänge, beantwortet und weitergeleitet. Die beiden Versandpfeile bleiben untereinander angeordnet.

Neben jedem sichtbaren Ordner steht die direkte Anzahl ungelesener Nachrichten dieses Ordners (ohne Unterordner). Der virtuelle Ordner **Ungelesen** enthält alle ungelesenen Nachrichten aus den für den Benutzer lesbaren Ordnern, unabhängig von Konto oder Ablage. Er speichert keine Kopien. Suche, Markiert-Filter und Nachladen funktionieren auch dort. Beim Öffnen wird eine Nachricht gelesen und verschwindet aus der Ungelesen-Liste, bleibt aber in der Vorschau geöffnet. **Als ungelesen markieren** nimmt sie wieder in die Liste auf. Fremde private Ordner und deren Nachrichten werden weder angezeigt noch mitgezählt.

Für bestehende Installationen wie gewohnt Datenbank und `.env` sichern, Server stoppen und `upgrade-db` ausführen. Das Upgrade ergänzt die gemeinsame `trusted`-Spalte und übernimmt die bisherigen Kontakte und expliziten Absenderfreigaben als gemeinsame Grundlage.


## Kontaktverknüpfungen und Maildarstellung

Die Zuordnung einer Absenderadresse zu einem Kontakt wird zusätzlich in `MessageContact` gespeichert. Beim Anlegen, Bearbeiten und Importieren von Kontakten sowie beim CardDAV-Abruf werden vorhandene Nachrichten aller Konten anhand der normalisierten Absenderadresse verknüpft und als vertraut markiert. Neue Nachrichten erhalten Kontaktverknüpfung und Vertrauensstatus direkt beim Import. Die Erkennung berücksichtigt Anzeigenamen und Groß-/Kleinschreibung der Adresse; andere Absenderadressen werden nicht mitverknüpft. Beim Ändern oder Löschen eines Kontakts werden Verknüpfungen neu abgeglichen; eine separat vergebene Absenderfreigabe bleibt wirksam. Ordnerrechte werden durch die Verknüpfung nicht erweitert.

Nach diesem Update bei gestopptem Server und gesicherter Datenbank `upgrade-db` ausführen. Es legt die Verknüpfungstabelle an und ordnet auch bereits bekannte Kontakte und Nachrichten zu. Wiederholtes Ausführen erzeugt keine doppelten Verknüpfungen.

Die HTML-Ansicht nutzt nach Möglichkeit die unveränderte MIME-Originalnachricht. Nicht sichtbare `head`-, `style`- und `script`-Blöcke werden einschließlich ihres Inhalts vor der Bereinigung entfernt. Dadurch erscheinen CSS-Regeln nicht mehr als führender Text, auch bei Nachrichten, deren gespeicherte HTML-Kopie bereits durch die frühere Bereinigung verändert wurde. Bereinigte Inline-Formatierung bleibt bei vertrauten Nachrichten erhalten.

Der gemeinsame Editor für neue Nachrichten, Antworten und Weiterleitungen besitzt eine obere Menüleiste mit **Nachricht senden** rechts. Der Button ist mit dem Nachrichtenformular verbunden; Pflichtfeldprüfung, Rich-Text-Übernahme und Anhänge bleiben Teil desselben Formulars.
