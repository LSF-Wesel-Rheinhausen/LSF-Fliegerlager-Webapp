# Arbeitsübergabe: von diesem Mac zu Codex Cloud

Ziel ist, Entwicklung, Tests, Reviews und PR-Arbeit in Codex Cloud fortzusetzen.
Die [Demo-Wiederherstellung](local-demo.md) ist dafür nur ein Baustein.
Diese Anleitung gehört zum Branch `codex/reproducible-local-demo` in PR #635, der auf PR #618 aufbaut.
Vor dem Einrichten prüfen, dass der ausgewählte Checkout diese Anleitung, die Skills und `scripts/local_demo.py`
enthält. Nach dem Merge den entsprechenden aktuellen `main`-Stand verwenden.

## Übertragener und verbleibender Zustand

| Bestandteil | Übergabe |
| --- | --- |
| Anwendung und Schema | Git-Checkout; ursprüngliche Codebasis `8b83db9bfbd842bd71b5b213e1c6c1319a53978f` |
| Beispieldaten | Versionierte, bereinigte Fixture; neue SQLite-Datei und lokale Testzugänge erzeugen |
| Agentenregeln | `AGENTS.md`, `CONTRIBUTING.md` und die [versionierten Skills](agent-skills.md) |
| Werkzeugstand des Macs | [Gemessener Stand](local-demo-runtime.json), einschließlich zusätzlicher Agentenwerkzeuge |
| Laufende Prozesse, Browserzustand, Cache | Im Cloud-Task neu starten beziehungsweise aufbauen |
| Zugang zu GitHub | In der Cloud verbinden und Lese-/Schreibberechtigungen prüfen |

Der Mac verwendete Python **3.12.16**, Node **26.13.0** und npm **11.20.0**.
Das Cloud-Ziel folgt dagegen dem Repository-/CI-Standard **Python 3.13 und Node 22**.
Eine kopierte macOS-`.venv` funktioniert unter Linux nicht. Python-Requirements enthalten Versionsbereiche;
das Laufzeitprotokoll ist keine vollständige Lockdatei. Hier wird derselbe Arbeitsablauf mit denselben
Fachdaten übertragen, keine bitidentische macOS-Maschine zugesichert. Die Cloud muss die Abnahme unten bestehen.

## 1. Cloud-Umgebung anlegen

In Codex **Work in → Cloud → Create environment** wählen und
`LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp` verbinden. Zugriff zunächst privat halten.
Codex kann Installation und Dienststart als **Install script** und **Start skill** speichern.
Nach erfolgreicher Abnahme veröffentlichen; Änderungen am wiederverwendbaren Setup erneut veröffentlichen.
Ein neuer Task erhält die veröffentlichte Ausgangsumgebung, ein bestehender Task seinen eigenen Zustand.
[Offizielle Cloud-Anleitung](https://learn.chatgpt.com/docs/environments/cloud-environments)

Dem Setup-Agenten diesen Auftrag geben:

```text
Richte dieses Repository gemäß docs/codex-cloud.md ein.
Lies AGENTS.md, CONTRIBUTING.md und docs/agent-skills.md.
Prüfe zuerst Checkout, Python-/Node-Version und den Arbeitsbaum.
Verwende eine neue Linux-.venv, requirements-dev.txt und npm ci.
Stelle die versionierte synthetische Demo her und übernimm die enthaltenen Repository-Skills.
Richte GitHub-Zugriff, Hooks, Graphify und RTK für Entwicklung und PR-Reviews ein.
Teste die unten genannten Abnahmekriterien. Melde fehlende Laufzeitfähigkeiten konkret.
Verändere keine Produktionssysteme und kopiere keine lokalen Credential-Verzeichnisse.
```

## 2. Installation im Repository-Stamm

Voraussetzungen: Python 3.13 mit `venv`, Node 22 mit npm, Git, Bash, `rg`, `curl`, `lsof` und GitHub CLI `gh`.
Unter Linux benötigt Playwright zusätzlich die vom Installer ermittelten Systembibliotheken.
Fehlende Systempakete im Cloud-Setup mit den dort erlaubten Rechten installieren lassen.

```bash
python3.13 --version
node --version
npm --version
git status --short
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm ci
.venv/bin/pre-commit install
.venv/bin/pre-commit install-hooks
npx playwright install --with-deps chromium firefox webkit
mkdir -p data
```

`npm ci` bewahrt den npm-Lock. Nicht das ältere `npm run codex:setup` verwenden: Es verwendet derzeit
`npm install` und wählt den Interpreter über `python`. `.venv/bin/pre-commit install` richtet die
versionierten Prüfungen ein; nicht zusätzlich `core.hooksPath=.githooks` setzen, da dies einen anderen,
zusätzlich die gesamte Python-Suite ausführenden Hook aktiviert. Bestehende Hooks vor Änderungen prüfen.
Die expliziten Tests bleiben unabhängig von Hooks verpflichtend.

Abhängigkeiten und Browser bei Manifest-/Lockänderungen erneut installieren. Ein vorhandenes
Demo-DB-File dabei weder löschen noch neu seeden. Ein neuer Cloud-Task darf nicht darauf angewiesen sein,
dass der Mac noch läuft oder dessen Dateipfade erreichbar sind.

## 3. Agentenwerkzeuge und Skills

Die Skills liegen unter `.agents/skills/` und werden zusammen mit dem Repository ausgecheckt.
Der [Skill-Katalog](agent-skills.md) beschreibt Umfang, Herkunft und Anpassungen. Im ersten Cloud-Task
prüfen, dass diese Skills angeboten werden; bei fehlender Discovery die benötigte `SKILL.md` ausdrücklich lesen.
Nicht das gesamte persönliche `.codex`-/`.agents`-Verzeichnis kopieren.

Zusätzliche Werkzeuge sind Entwicklungswerkzeuge, keine neuen App-Abhängigkeiten:

| Werkzeug | Mac-Stand | Cloud-Einrichtung |
| --- | --- | --- |
| GitHub CLI | 2.103.3 | Linux-Paket/Image verwenden; `gh --version` prüfen |
| RTK | 1.1.0 | Passendes Linux-Release aus [rtk-ai/rtk](https://github.com/rtk-ai/rtk/blob/develop/INSTALL.md) installieren; Herkunft und Version prüfen |
| Graphify | 0.8.27 | Separates Tool-venv aus dem PyPI-Paket `graphifyy`; nicht in App-Requirements aufnehmen |
| agent-browser | 0.33.1 | Skill synchronisiert; Ausführung nur bei tatsächlich unterstützter Browserfähigkeit |

Für den gemessenen Graphify-Stand beispielsweise:

```bash
python3.13 -m venv .cache/graphify-venv
.cache/graphify-venv/bin/python -m pip install graphifyy==0.8.27
.cache/graphify-venv/bin/graphify --version
.cache/graphify-venv/bin/graphify update .
```

Den Toolpfad in der Cloud-Umgebung für spätere Task-Shells verfügbar machen oder explizit verwenden.
Ein einmaliges `export PATH=...` in einer Installations-Shell allein ist keine zuverlässige Übergabe.
Graphify danach zuerst mit `graphify query "<Frage>"` nutzen; generierte Graphdateien bleiben ignoriert.
[Graphify-Quelle](https://github.com/Graphify-Labs/graphify)

RTK anschließend mit `rtk --version` prüfen. Für vollständige Diagnosen `rtk proxy <Befehl>` verwenden.
Nicht unbesehen `cargo install rtk` ausführen: Das gleichnamige Registry-Paket kann ein anderes Projekt sein.
Keine Änderungen an Shell-/Agenten-Hooks fremder Projekte vornehmen.

Die aktuelle Cloud-Dokumentation nennt Computer-/Browserbedienung als nicht unterstützt und persönliche
lokale Skills als nicht synchronisiert. Deshalb UI-Bedienung nicht zusichern oder Schutzmechanismen umgehen.
Ob die CLI-Browserprüfungen hier laufen, ist durch die Abnahme zu prüfen; fehlende Fähigkeit ausdrücklich melden
und die unveränderte CI-Matrix verwenden. Für eine Umgebung mit freigegebener Browserausführung beschreibt
[agent-browser](https://agent-browser.dev/installation) die Installation; zunächst `agent-browser skills get core` lesen.
[Cloud-Grenzen](https://learn.chatgpt.com/docs/environments/cloud-environments#current-limitations)

## 4. Konfiguration und GitHub-Zugriff

Für die synthetische Demo werden keine Produktions-Secrets benötigt. `local_demo.py serve` setzt SQLite,
lokale Anmeldung, Debug/HTTP und deaktivierte externe Integrationen selbst. Keine Produktions-`.env`,
Portainer-/GHCR-Zugangsdaten, SSH-Schlüssel, Keychains oder Browserprofile übertragen.

GitHub über die Cloud-Verbindung autorisieren. Git-Checkout, `gh`-API-Zugriff und Push sind separat zu prüfen:

```bash
git remote -v
git ls-remote origin HEAD
gh api repos/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp --jq '{full_name, permissions}'
gh pr view 635 --json url,isDraft,baseRefName,headRefName
git config user.name
git config user.email
```

Keine Identität erfinden. Einen nur lesenden Zugriff nicht als Push-Freigabe melden. Fehlende GitHub-CLI-
Authentifizierung über die Cloud-Konfiguration ergänzen lassen; keine lokalen Token-Dateien kopieren oder
Tokens in Git-URLs, Logs oder Setup-Skripten speichern. Netzwerkzugriffe auf benötigte Paketquellen,
Browserdownloads und GitHub begrenzen. Proxy-/CA-Einstellungen der Plattform erhalten.
Optionale HTTPS-Zugangswerte über die dafür vorgesehene Cloud-Verwaltung konfigurieren, keine Werte hier eintragen.
[Cloud-Verbindungen und Werte](https://learn.chatgpt.com/docs/environments/cloud-environments)

## 5. Dienste und Daten pro Task starten

Als Startanweisung der Cloud-Umgebung hinterlegen:

```text
Wechsle zum Repository-Stamm und prüfe den Arbeitsbaum.
Wenn data/local-demo.sqlite3 fehlt: Erzeuge sie mit scripts/local_demo.py create.
Wenn sie vorhanden ist: Nur verify ausführen, niemals automatisch ersetzen oder reseeden.
Starte scripts/local_demo.py serve auf einem freien Loopback-Port.
Prüfe /healthz/ und notiere Datenbankpfad, Port und Prozess-/Terminal-ID für die Fortsetzung.
Erhalte Änderungen im bestehenden Task; ein neuer Task startet mit einem eigenen Datenbestand.
```

Für die exakt dokumentierten Beispieldaten:

```bash
.venv/bin/python scripts/local_demo.py create --database data/local-demo.sqlite3 --reference-date 2026-11-03
.venv/bin/python scripts/local_demo.py verify --database data/local-demo.sqlite3
.venv/bin/python scripts/local_demo.py serve --database data/local-demo.sqlite3 --port 8000
```

`create` nur bei fehlender Zieldatei ausführen. Ohne `--reference-date` bleibt das aktive Lager relativ
zu heute nutzbar. Konten, beide PIN-Schritte und Szenarien stehen in [local-demo.md](local-demo.md).
`localhost:8000` im eigenen Laptop-Browser ist nicht der Cloud-Container. Einen Zugriff nur über einen
tatsächlich angebotenen, privaten Plattformzugang verwenden; die Demo nicht öffentlich exponieren.
Für agentenseitige Requests im Container genügt `curl --fail http://127.0.0.1:8000/healthz/`.
Nicht `codex:start` benutzen, da es den Server an alle Interfaces bindet.

Für eigenständige Django-Kommandos in derselben Task-Shell explizit die Demo-Datei wählen:

```bash
export DATABASE_URL="sqlite:///$PWD/data/local-demo.sqlite3"
export DJANGO_DEBUG=1
export DJANGO_HTTPS=0
export DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
export AUTHELIA_SSO_ENABLED=0
export PASSKEY_ENABLED=0
export WEB_PUSH_ENABLED=0
export UPDATE_AGENT_URL=
export UPDATE_AGENT_TOKEN=
export ACCOUNT_RECOVERY_PUBLIC_ORIGIN=http://localhost:8000
```

Diese Werte in neuen Task-Shells erneut setzen oder passend zum tatsächlichen Checkout in der Cloud
konfigurieren. E2E-Worker verwenden eigene Datenbanken und Ports; niemals die Demo-Datei zum E2E-Reset verwenden.

## 6. Abnahme und täglicher Arbeitsablauf

```bash
.venv/bin/python scripts/local_demo.py verify --database data/local-demo.sqlite3
.venv/bin/python src/manage.py check
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src
.venv/bin/python -m pytest tests/test_local_demo.py
.venv/bin/python -m pytest -n 4 --dist=loadfile --ignore=tests/test_migrations.py
.venv/bin/python -m pytest tests/test_migrations.py
npm run test:e2e
```

Diese Einzelbefehle funktionieren auch dann als Prüfplan, wenn `CI=true` den lokalen Komfortwrapper
`npm run test:local` absichtlich ablehnt. Keine Tests für Cloud-Beschränkungen abschwächen.
PostgreSQL-16-, Container-, DAST- und Workflow-Prüfungen weiterhin in der vorhandenen GitHub-Pipeline ausführen;
SQLite ersetzt diese Prüfungen nicht. Docker-Verfügbarkeit nicht voraussetzen.

Vor Übergabe festhalten: Checkout-SHA, tatsächliche Toolversionen, zwölf entdeckte Skills, geprüfter
GitHub-Zugriff, Datenbank/Healthcheck, bestandene Prüfungen und konkrete offene Fähigkeitsgrenzen.
Die Cloud-Einrichtung wurde durch diesen lokalen Dokumentations-PR noch nicht ausgeführt oder abgenommen.

Danach wie bisher arbeiten: Graphify für Codebeziehungen, Scope/Plan gemäß `AGENTS.md`, kostengünstige
Subagents mit Budget, TDD, fokussierte und vollständige Prüfungen, nur eigene Dateien committen,
Task-Branch und Draft-PR, Review-Threads einschließlich Inline-Kommentaren prüfen. Ready for Review erst
nach grüner letzter Pipeline. CI-Überwachung richtet sich nach Jans jeweiliger Anweisung.
