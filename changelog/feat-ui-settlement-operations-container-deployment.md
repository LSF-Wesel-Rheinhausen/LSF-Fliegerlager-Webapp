# Optimiertes Container-Deployment mit Admin-Updates

## Zusammenfassung

- Das Compose-Deployment verwendet direkt die veröffentlichten GHCR-Images.
- Superuser können verfügbare App-Updates samt letztem Change prüfen und installieren.
- Ein isolierter Agent erstellt vor Updates ein PostgreSQL-Backup, prüft den Healthcheck und führt bei Fehlern ein Image-Rollback aus.
- WhiteNoise stellt statische Dateien im Gunicorn-Container bereit.

## Geänderte Bereiche

- Dockerfiles, Compose- und Umgebungsbeispiele sowie GitHub-Actions-Publishing
- Deployment-Agent und superusergeschützte Update-Oberfläche
- Betriebs- und Deployment-Dokumentation

## Tests

- Django-Systemcheck, Pytest, Ruff und MyPy
- Image- und Compose-Validierung in GitHub Actions
