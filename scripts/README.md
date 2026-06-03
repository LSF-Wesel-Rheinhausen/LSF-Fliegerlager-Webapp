# `scripts`

Lokale Hilfsskripte nach dem Muster des Windenbuch-Projekts.

- `codex-setup.sh`: Erstellt `.venv`, installiert Python- und Node-Abhaengigkeiten.
- `codex-start.sh`: Fuehrt Migrationen aus und startet den Django-Entwicklungsserver auf `0.0.0.0:8000`.
- `codex-cleanup.sh`: Entfernt lokale Caches und Testartefakte.
- `start-e2e.sh`: Startet den isolierten Django-Server fuer Playwright mit SQLite-Testdatenbank und Test-Env-Variablen.
- `test-local.sh`: Fuehrt Ruff-Lint, Ruff-Formatcheck, Django-Check, Pytest und Playwright aus. Ergebnisse und Einzel-Logs landen unter `.test-local-logs/<timestamp>/`.
