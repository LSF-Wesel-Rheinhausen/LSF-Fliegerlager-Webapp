# Tägliche Abrechnungshistorie und Backup-Archive

## Zusammenfassung

- Abrechnungsläufe unterscheiden jetzt zwischen manuellen Läufen und automatischen täglichen Backup-Läufen.
- Die Updates-Seite erlaubt Superusern, tägliche Settlement-Backups zu aktivieren und die Uhrzeit zu setzen.
- Ein Scheduler-Command erzeugt zur fälligen Uhrzeit genau einen täglichen Lauf für das aktive Lager.
- Backup-Archive enthalten PostgreSQL-Dump, CSV, Excel, PDF-Rechnungen aus Snapshots und ein Manifest.
- Der Updater-Agent bietet dafür einen internen `POST /backup`-Endpunkt mit Pfad-Traversal-Schutz.

## Tests

- Scheduler-Fälligkeit, Deduplizierung, fehlendes aktives Lager und Export-Staging.
- Superuser-/Nicht-Superuser-Zugriff auf die Backup-Einstellungen.
- Agent-Archivierung und Pfad-Traversal-Abwehr.
- Django-Check, Migrationsprüfung, Ruff, mypy, Pytest und Playwright bestanden.
