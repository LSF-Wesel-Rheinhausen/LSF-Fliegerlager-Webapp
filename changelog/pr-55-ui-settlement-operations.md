# Teilnehmerarchiv, Abrechnungsläufe und Docker-Betrieb

## Zusammenfassung

- Teilnehmer können bearbeitet, ohne Datenverlust archiviert und wiederhergestellt werden.
- Genau ein Lager ist aktiv; nur dessen nicht archivierte Teilnehmer erscheinen im Kiosk.
- Lagerabrechnungen lassen sich als unveränderliche Versionen speichern und historisch als CSV, Excel und PDF exportieren.
- Docker Compose prüft PostgreSQL und Django per Healthcheck.
- PostgreSQL-Backups und bestätigungspflichtige Wiederherstellungen sind über Skripte dokumentiert.

## Tests

- Teilnehmerarchivierung, Rollen und Kiosk-Sichtbarkeit.
- Versionsvergabe, Snapshot-Unveränderlichkeit und historische Exporte.
- Healthcheck bei erreichbarer und ausgefallener Datenbank.
- Django-Check, Migrationsprüfung, 224 Pytest-Fälle, Ruff und mypy bestanden.
- Der Playwright-Lauf benötigt eine lokale Serverfreigabe und konnte wegen des Umgebungslimits nicht abgeschlossen werden.
