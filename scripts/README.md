# `scripts`

Lokale Hilfsskripte nach dem Muster des Windenbuch-Projekts.

- `codex-setup.sh`: Erstellt `.venv`, installiert Python- und Node-Abhaengigkeiten.
- `codex-start.sh`: Fuehrt Migrationen aus und startet den Django-Entwicklungsserver auf `0.0.0.0:8000`; fuer rein lokale Nutzung kann direkt `python src/manage.py runserver 127.0.0.1:8000` verwendet werden.
- `codex-cleanup.sh`: Entfernt lokale Caches und Testartefakte.
- `start-e2e.sh`: Bereinigt veraltete Testserver, startet den isolierten Django-Server fuer Playwright mit SQLite-Testdatenbank und beendet ihn nach dem Lauf kontrolliert.
- `seed_local_test_db`: Der Management-Command erzeugt die gemeinsame synthetische lokale Testdatenbank idempotent. `start-e2e.sh` nutzt ihn nur bei `SEED_LOCAL_TEST_DB=1`; standardmäßig bleiben E2E-Daten pro Worker isoliert.
- `test-local.sh`: Fuehrt Ruff-Lint, Ruff-Formatcheck, Django-Check, Pytest und Playwright aus. Pytest nutzt plattformunabhaengig standardmaessig vier Worker; `PYTEST_WORKERS=0 npm run test:local` behaelt den seriellen Fallback. Fuer ressourcenarme Systeme kann die Worker-Zahl beispielsweise mit `PYTEST_WORKERS=2` reduziert werden. Migrationstests laufen wegen ihrer Schemaaenderungen immer separat seriell. Ergebnisse und Einzel-Logs landen unter `.test-local-logs/<timestamp>/`.
- `postgres-backup.sh`: Erstellt ein komprimiertes, zeitgestempeltes PostgreSQL-Backup unter `BACKUP_DIR`.
- `postgres-restore.sh`: Spielt nach expliziter Freigabe mit `RESTORE_CONFIRM=YES` ein Backup aus `BACKUP_DIR` ein.
