## Portainer-basierter Update-Agent

- Update-Agent von Docker-Socket/Compose-Steuerung auf Portainer-API umgestellt.
- `APP_IMAGE` wird über Stack-ENV aktualisiert und bei Fehlern auf den vorherigen Wert zurückgesetzt.
- Backups laufen über `DATABASE_URL` und `pg_dump`; Healthchecks nutzen `APP_HEALTH_URL`.
- Deployment-Beispiele und Doku um Portainer-ENV, minimale API-Key-Rechte und optionales `GHCR_TOKEN` ergänzt.
