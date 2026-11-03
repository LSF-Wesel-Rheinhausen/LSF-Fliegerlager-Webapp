# Übergabe: lokale Entwicklungsumgebung mit Dummy-Daten

## Ausgangsstand

- Reproduziert die am 3. November 2026 geprüfte Umgebung: Codebasis PR #618,
  Commit `8b83db9bfbd842bd71b5b213e1c6c1319a53978f`, isolierte SQLite-Datenbank und lokale Anmeldung.
- Diesen separaten Daten-/Dokumentations-Branch verwenden, der auf `fix/602-environment-updater` aufbaut.
- Die Fachdatensätze liegen in [`../tests/fixtures/local_demo.json`](../tests/fixtures/local_demo.json).
  Die lokale SQLite-Datei wird daraus erzeugt und bleibt im ignorierten Verzeichnis `data/`.
- Die gemessenen Werkzeugversionen stehen in [`local-demo-runtime.json`](local-demo-runtime.json).
  Das ist ein Ist-Protokoll, keine Dependency-Lockdatei oder Aufforderung zum Downgrade.
- `AGENTS.md` und `CONTRIBUTING.md` gelten weiterhin. Fremde Änderungen, insbesondere `.content`, erhalten.

## 1. Python und Arbeitskopie vorbereiten

Für eine neue Arbeitskopie den Übergabe-Branch auschecken:

```bash
git clone --branch codex/reproducible-local-demo --single-branch \
  https://github.com/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp.git LSF-local-demo
cd LSF-local-demo
```

Alle Befehle vom Repository-Stamm aus ausführen. Einen bereits laufenden Testserver und seine Arbeitskopie
erhalten. Auf demselben Rechner kann die vorhandene virtuelle Umgebung der Hauptarbeitskopie wiederverwendet werden:

```bash
demo_main_checkout="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
demo_python="$demo_main_checkout/.venv/bin/python"
"$demo_python" --version
```

Die Bestandsumgebung verwendete Python 3.12.16 und Django 6.1. Für eine neue Installation gilt der
Projektstandard Python 3.13 mit den aktuellen Requirement-Dateien. Ältere gemessene Toolstände nicht
durch einen Downgrade der Projektanforderungen erzwingen:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
demo_python="$PWD/.venv/bin/python"
```

Für Browserprüfungen zusätzlich die vorhandene Node-Umgebung und den npm-Lock verwenden:

```bash
npm ci
npx playwright install
```

## 2. Datenbank wiederherstellen

```bash
"$demo_python" scripts/local_demo.py create \
  --database data/local-demo.sqlite3 \
  --reference-date 2026-11-03
"$demo_python" scripts/local_demo.py verify --database data/local-demo.sqlite3
```

- Die Zieldatei muss neu sein; bestehende Datenbanken und Symlinks werden nicht überschrieben.
- Mit `--reference-date 2026-11-03` gilt der dokumentierte Lagerzeitraum **31. Oktober bis 10. November 2026**.
- Ohne `--reference-date` werden fachliche Datumswerte relativ auf den heutigen Tag verschoben.
  Geburtstage bleiben erhalten; gebuchte und tatsächliche Nächte werden passend gesetzt.
- Zum erneuten Aufbau einen anderen neuen Dateinamen wählen. Bestehende Testdaten können eigene Szenarien enthalten.
- Nach dem Import **nicht** zusätzlich `seed_local_test_db` ausführen: Der Basis-Seed verwendet August-Daten
  und würde den abgestimmten Demo-Zustand verändern.

## 3. Server starten

Prüfen, ob Port 8000 bereits verwendet wird:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Ist der Port frei:

```bash
"$demo_python" scripts/local_demo.py serve --database data/local-demo.sqlite3 --port 8000
```

Bei einem bereits laufenden Server einen freien anderen Port verwenden, etwa `--port 8001`.
Keinen fremden Prozess beenden. Der Server läuft im Vordergrund; nur den selbst gestarteten Prozess mit
`Ctrl+C` beenden. In einer Agentensitzung die Prozess-/Terminal-ID für die nächste Übergabe notieren.

- Startseite: <http://localhost:8000/>
- Verwaltungslogin: <http://localhost:8000/login/>
- Kiosk: <http://localhost:8000/kiosk/>
- Healthcheck: <http://127.0.0.1:8000/healthz/>

Bei einem anderen Port die URLs anpassen. Der Helfer bindet ausschließlich an `127.0.0.1`, verwendet die
ausdrücklich gewählte SQLite-Datei und setzt Debug-/HTTPS-Einstellungen für die lokale Umgebung.
Push und externe Updater-Anbindung sind deaktiviert; SMTP bleibt ausgeschaltet.

## Lokale Testkonten und PIN-Ablauf

Die Zugangswerte stammen ausschließlich aus dem bereits vorhandenen
[`seed_local_test_db`](../src/billing/management/commands/seed_local_test_db.py).
Die Fixture enthält keine verwendbaren Passwort-/PIN-Hashes. Diese werden beim Wiederherstellen lokal neu gesetzt.

| Zweck | Benutzer oder Person | Definition im Basis-Seed |
| --- | --- | --- |
| Admin/Superuser | `local-admin` | `ADMIN_PASSWORD` |
| Normaler Nutzer/Bearbeiter | `local-editor` | `EDITOR_PASSWORD` |
| HÜbers | `local-huebers` | `HUEBERS_PASSWORD` |
| Gemeinsamer Lagerzugang | `/kiosk/access/` | `SHARED_KIOSK_PIN` |
| Persönlicher Kiosk-Zugang | `AdultComplete Synthetic` | `_seed_participants()` |
| Begleitperson | `FamilyCompanion Synthetic` | `_seed_family()` |

Für den Kiosk zuerst den Lagerzugang entsperren, dann die Person auswählen und deren persönlichen PIN eingeben.
Zusätzlich gibt es einen inaktiven Nutzer, eine gesperrte Teilnehmer-PIN und Datensätze mit fehlenden Angaben.
Diese Fälle dienen absichtlich der Prüfung von Sperr-, Freigabe- und Fehlerzuständen.

## Datenumfang

| Bereich | Ausgangsbestand |
| --- | --- |
| Lager | 3: aktiv, zukünftig, archiviert |
| Verwaltungsnutzer | 4: Admin, Bearbeiter, HÜbers, inaktiv |
| Teilnehmer/Familie | 6 Teilnehmer, 3 Familienmitglieder, 1 angenommene Buchungsverknüpfung |
| Anwesenheit | 8 Einträge mit eigenen, Familien- und Randfällen |
| Essen | 4 Menüeinträge, 3 Buchungen, 1 Bestellung, 2 Buchungs-Overrides |
| Abrechnung | 7 Preise, 7 Kostenpositionen, 3 Zahlungen, 6 Auslagen, 1 Umlage |
| Gespeicherte Abrechnungen | 2 Läufe und 2 Teilnehmerabrechnungen |
| Dienste | 3 Vorlagen, 1 Ausnahme, 32 Dienste, 3 Besetzungen, ein Tauschangebot |
| Weitere Beispiele | 2 Lagermeldungen, 2 Getränkebuchungen, offene Teilnehmerfreigabe |

Sitzungen, Recovery-Tokens, Passkeys, Push-Abonnements, Versandwarteschlangen, externe Zugangskonfigurationen
und Laufzeitspuren gehören nicht zum geteilten Snapshot. Diese Integrationen benötigen separate lokale Testkonfigurationen.

## 4. Ergebnis prüfen

```bash
"$demo_python" scripts/local_demo.py verify --database data/local-demo.sqlite3
curl --fail http://127.0.0.1:8000/healthz/
```

Im Browser einmal Admin und Bearbeiter anmelden und wieder abmelden. Anschließend den Kiosk in einer frischen
Sitzung öffnen und den zweistufigen PIN-Login prüfen. Die aktuelle Live-Abrechnung muss als PDF erreichbar sein.
Die ursprüngliche Umgebung wurde einschließlich dieser Logins und des PDF-Exports geprüft.

Für Änderungen am Helfer oder Snapshot die zugehörigen Regressionstests und anschließend die
Repository-Prüfungen aus `CONTRIBUTING.md` ausführen. Socket- und Browserprüfungen benötigen gegebenenfalls
eine genehmigte Ausführung außerhalb der Sandbox: Genehmigung anfragen und Tests nicht überspringen.

Beim Übergabelauf bestanden die Python-Prüfungen sowie Chromium und WebKit. Der lokal installierte
Firefox scheiterte auch außerhalb der Sandbox schon beim isolierten Start mit
`sandbox_extension_issue_file_to_process` und `RenderCompositorSWGL failed mapping default framebuffer`.
Das ist keine erfolgreiche Firefox-Verifikation; auf einem anderen Rechner beziehungsweise in der CI
die unveränderte vollständige Browsermatrix ausführen.

## Datenschutz bei einer Aktualisierung

- Den Snapshot ausschließlich aus einer neu erzeugten synthetischen Demo-Umgebung aufbauen.
- Keine laufende oder produktive SQLite-Datei veröffentlichen.
- Die Modell-Allowlist und Sicherheitsprüfungen des Helfers beibehalten.
- Keine Sitzungen, Tokens, verwendbaren Passwort-/PIN-Hashes, SMTP-Credentials, Uploads oder realen Kontaktdaten hinzufügen.
- Nach Änderungen eine neue leere Datenbank aus der versionierten Fixture erstellen und Zugänge,
  Datumsbereiche, Beziehungen und Datenumfang erneut prüfen.
