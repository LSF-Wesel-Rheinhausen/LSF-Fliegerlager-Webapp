# PR 1: F-01/F-03 Push-Egress und Secret-Isolation

## Zusammenfassung

- Entferne die pauschale `.env`-Vererbung aus App-, Backup-, Push- und E-Mail-Worker.
- Begrenze Portainer-/Registry-Secrets auf den Updater und dokumentiere die Service-Allowlists.
- Erlaube Web-Push-Subscriptions nur für explizit konfigurierte HTTPS-Origins und revalidiere Legacy-Datensätze
  unmittelbar vor der Zustellung.
- Zustellungen verwenden eine redirect-freie Requests-Session mit kurzem Timeout.

## Geänderte Dateien

- `docker-compose.yml`
- `deploy/docker-compose.example.yml`
- `deploy/.env.example`
- `deploy/README.md`
- `.env.example`
- `src/billing/models.py`
- `src/billing/notification_views.py`
- `src/billing/notifications.py`
- `src/billing/push_endpoints.py`
- `src/config/settings.py`
- `tests/conftest.py`
- `tests/test_compose_configuration.py`
- `tests/test_notifications.py`

## Tests

- Fokussierte Compose- und Web-Push-Regressionstests.
- Vollständige lokale Pflichtsuite, Compose-Validierung, Ruff, Django-Check und mypy folgen vor dem Commit.

## Offene Punkte

- Die produktiven Push-Origins müssen vom Betreiber aus der realen Browser-/Push-Service-Konfiguration eingetragen
  werden; bis dahin bleibt die Liste leer und Push fail-closed.
