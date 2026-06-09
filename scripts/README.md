# `scripts`

Lokale Hilfsskripte nach dem Muster des Windenbuch-Projekts.

- `codex-setup.sh`: Erstellt `.venv`, installiert Python- und Node-Abhaengigkeiten.
- `codex-start.sh`: Fuehrt Migrationen aus und startet den Django-Entwicklungsserver auf `0.0.0.0:8000`; fuer rein lokale Nutzung kann direkt `python src/manage.py runserver 127.0.0.1:8000` verwendet werden.
- `codex-cleanup.sh`: Entfernt lokale Caches und Testartefakte.
- `start-e2e.sh`: Bereinigt veraltete Testserver, startet den isolierten Django-Server fuer Playwright mit SQLite-Testdatenbank und beendet ihn nach dem Lauf kontrolliert.
- `test-local.sh`: Fuehrt Ruff-Lint, Ruff-Formatcheck, Django-Check, Pytest und Playwright aus. Ergebnisse und Einzel-Logs landen unter `.test-local-logs/<timestamp>/`.
