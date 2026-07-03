# Dependency Graph Audit

Stand: 2026-07-03

## Ergebnis

Der Runtime-Dependency-Graph ist bereits klein. Es gibt aktuell keine offensichtliche Abhängigkeit, die ohne Featureverlust entfernt werden kann.

## Runtime Python

- `Django`: Kernframework.
- `dj-database-url`: ENV-basierte Datenbankkonfiguration.
- `gunicorn`: Produktions-WSGI-Server.
- `openpyxl`: XLSX-Importe und -Exporte.
- `psycopg[binary]`: PostgreSQL-Treiber für Docker/Deployment.
- `reportlab`: PDF-Exporte.
- `whitenoise`: statische Dateien im Container.

## Updater

Der Update-Agent verwendet nur die Python-Standardbibliothek. Für Portainer mit Self-Signed-Zertifikat wird weiterhin keine neue Dependency benötigt; die TLS-Option nutzt `ssl`.

## Node

- `@playwright/test`: E2E-Tests und Layout-Prüfungen.

## Reduktionskandidaten

- `psycopg[binary]`: Kann langfristig durch `psycopg` plus Systembibliotheken ersetzt werden, wenn das Docker-Image bewusst auf kleinere native Layer umgestellt wird.
- `openpyxl`: Nur entfernbar, wenn XLSX-Funktionalität gestrichen oder optional ausgelagert wird.
- `reportlab`: Nur entfernbar, wenn PDF-Export gestrichen oder optional ausgelagert wird.
- `pytest-cov`: Nur entfernen, wenn lokale oder CI-Coverage-Auswertung nicht mehr genutzt wird.

## Empfehlung

Vor einem Dependency-Abbau sollte das Projekt auf einen deterministischen Lockfile-Workflow wechseln, zum Beispiel `uv` oder Poetry. Danach kann die tatsächliche Transitive-Dependency-Fläche mit reproduzierbaren Builds verglichen werden.
