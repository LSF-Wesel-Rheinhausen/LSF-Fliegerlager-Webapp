# Synchronisierte Entwicklungs-Skills

Diese zwölf Skills werden aus `.agents/skills/` mit Git ausgecheckt und sind damit unabhängig vom
persönlichen Skill-Verzeichnis dieses Macs. In Codex Cloud zuerst die Discovery prüfen; wenn ein Skill
nicht angeboten wird, seine `SKILL.md` ausdrücklich lesen. Skills installieren keine CLI-Binaries.

| Skill | Zweck |
| --- | --- |
| `cost-aware-subagent-orchestrator` | Budget, günstige Delegation und begrenzte Review-/Testläufe |
| `graphify` | Codebeziehungen und Wissensgraph abfragen/aktualisieren |
| `agent-browser` | Versionspassende CLI-Anleitung für autorisierte Browserarbeit, sofern unterstützt |
| `address-github-comments` | GitHub-Reviewhinweise bearbeiten |
| `commit` | Conventional Commits und sichere Task-Branches |
| `test-driven-development` | Verhalten vor oder zusammen mit Implementierung testen |
| `systematic-debugging` | Ursachen vor Änderungen untersuchen |
| `verification-before-completion` | Abschlussaussagen durch aktuelle Prüfergebnisse belegen |
| `django-pro` | Django-Modelle, Views, ORM und Architektur |
| `python-testing-patterns` | Pytest, Fixtures und Tests an I/O-Grenzen |
| `python-pro` | Python-Implementierung und Typen |
| `threat-modeling-expert` | Vertrauensgrenzen, Sicherheitsarchitektur und Risiken |

## Herkunft und gezielte Portierung

Ausgewählter Snapshot der lokal installierten Skill-Inhalte vom 3. November 2026, einschließlich der
referenzierten TDD-/Debugging-/Pytest-Ressourcen. Der Orchestrator war bereits versioniert.
Herkunftsangaben der importierten Skills bleiben in deren `metadata` erhalten; fehlende Lizenzangaben
werden nicht erfunden. System-/Plugin-Skills und persönliche Konfigurationen sind kein Bestandteil dieses Pakets.

Für die Portierung wurden zusätzliche Frontmatter-Felder unter `metadata` abgelegt, der Discovery-Text
für agent-browser gekürzt, lokale Skillnamen-Verweise berichtigt und beim Django-Skill ein bereits im
Quellbestand fehlendes Playbook nicht mehr verlinkt. Der Commit-Skill folgt dem Repository-Verbot für
KI-Co-Autoren und benötigt keinen separaten `create-branch`-Skill.
Graphify verwendet ausschließlich vorhandene Installationen beziehungsweise den isolierten Tool-Aufbau
und hält das Orchestrierungsbudget ein. Ein JavaScript-Helfer mit hier nicht vorhandenem `npm test`
wurde durch eine passende Debugging-Anweisung ersetzt; Quellbeispielpfade wurden neutralisiert.

`AGENTS.md`, aktuelle Nutzerfreigaben und Plattformregeln haben Vorrang: Skills erteilen weder
Produktionszugriff noch das Recht, Nachrichten zu versenden, neue Abhängigkeiten aufzunehmen oder
Sandbox-/Netzwerkgrenzen zu umgehen. Fehlende Browser- oder Subagent-Fähigkeiten konkret melden.
Keine Cloud-Fähigkeit allein aus dem Vorhandensein eines Skills ableiten.

## Aktualisieren

Nur die für das Repository benötigten Skill-Dateien und ihre tatsächlich referenzierten Ressourcen
gezielt übernehmen. Änderungen wie Code prüfen, relative Links und Frontmatter validieren, auf
Secrets/lokale Pfade prüfen und per PR versionieren. Keine automatische Synchronisation des gesamten
Home-Verzeichnisses und keine Symlinks zurück auf den Mac anlegen. Die Git-Historie versioniert diesen Snapshot.
