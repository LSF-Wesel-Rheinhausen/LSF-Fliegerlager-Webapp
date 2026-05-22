# `scripts`

Lokale Hilfsskripte nach dem Muster des Windenbuch-Projekts.

- `codex-setup.sh`: Erstellt `.venv`, installiert Python- und Node-Abhaengigkeiten.
- `codex-start.sh`: Fuehrt Migrationen aus und startet den Django-Entwicklungsserver.
- `codex-cleanup.sh`: Entfernt lokale Caches und Testartefakte.
- `start-e2e.sh`: Startet den isolierten Django-Server fuer Playwright mit SQLite-Testdatenbank.
- `test-local.sh`: Fuehrt Django-Check, Pytest und Playwright mit Logausgabe aus.
