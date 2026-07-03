# Portainer-Deployment

Für den Deployment-Host werden Portainer Business Edition, Docker Engine und Zugriff auf GHCR benötigt. Das Repository
muss nicht geklont werden; die beiden Beispieldateien können in einen Portainer-Stack übernommen werden.

```bash
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
mkdir -p backups
```

In `.env` müssen mindestens `DJANGO_SECRET_KEY`, `UPDATE_AGENT_TOKEN`, `UPDATE_AGENT_URL`, `POSTGRES_PASSWORD`,
`DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `PORTAINER_URL`, `PORTAINER_API_KEY`,
`PORTAINER_ENDPOINT_ID` und `PORTAINER_STACK_ID` angepasst werden. `POSTGRES_PASSWORD` und das Passwort innerhalb von
`DATABASE_URL` müssen identisch sein.

Pflichtvariablen für den Update-Agent:

- `UPDATE_AGENT_TOKEN`: internes Bearer-Token zwischen Django und Updater.
- `UPDATE_AGENT_URL`: interne Django-Adresse des Updaters; im Compose-Beispiel `http://updater:8080`.
- `APP_IMAGE`: Ziel-Image, das der Updater in Portainer als Stack-Variable setzt.
- `DATABASE_URL`: PostgreSQL-Verbindung für `pg_dump`-Backups.
- `PORTAINER_URL`: Portainer-Basis-URL, zum Beispiel `https://portainer.example.org` oder `https://host:9443`.
- `PORTAINER_API_KEY`: API-Key eines dedizierten technischen Portainer-Benutzers.
- `PORTAINER_ENDPOINT_ID`: Portainer Environment/Endpoint-ID des Ziel-Stacks.
- `PORTAINER_STACK_ID`: Portainer Stack-ID des Ziel-Stacks.

Optionale Variablen mit Defaults:

- `UPDATER_IMAGE`: Updater-Container-Image; Default ist das veröffentlichte GHCR-Updater-Image.
- `UPDATE_HEALTH_TIMEOUT`: maximale Wartezeit auf `APP_HEALTH_URL` in Sekunden; Default `180`.
- `APP_HEALTH_URL`: Healthcheck-URL der App; Default `http://app:8000/healthz/`.
- `TARGET_SERVICE`: Compose-Service des App-Containers für Rollback-Digest-Ermittlung; Default `app`.
- `BACKUP_DIR`: Host-Verzeichnis für Backups; Default `./backups`.
- `GHCR_TOKEN`: nur für private GHCR-Images setzen; bei öffentlichen Images leer lassen.
- `TZ`: Zeitzone des Updaters; Default `Europe/Berlin`.

```bash
docker compose pull
docker compose up -d
docker compose ps
curl http://127.0.0.1:8000/healthz/
```

Standardmäßig bindet die App nur an `127.0.0.1:8000`, passend für einen Reverse Proxy auf demselben Host. Für einen
direkten Zugriff im lokalen Netz kann `APP_BIND_ADDRESS=0.0.0.0` gesetzt werden. Bei HTTPS hinter einem kontrollierten
Proxy bleiben `DJANGO_HTTPS=1` und `DJANGO_TRUST_PROXY_SSL_HEADER=1` aktiv.

## Updates

Ein Django-Superuser öffnet **Updates**, prüft das bereitgestellte `latest`-Image und bestätigt die Installation. Der
Updater liest die OCI-Metadaten aus GHCR, ermittelt vor dem Update den unveränderlichen `repo@sha256:...`-Digest des
laufenden App-Containers, erstellt ein Backup unter `BACKUP_DIR`, setzt `APP_IMAGE` über die Portainer-API und wartet
auf `APP_HEALTH_URL`. Schlägt der Start fehl, setzt der Updater `APP_IMAGE` auf den vorher ermittelten Digest zurück
und redeployt den Stack erneut. Datenbankmigrationen werden nicht automatisch zurückgerollt; das erzeugte Backup bleibt
für eine kontrollierte Wiederherstellung erhalten.

Der Updater erhält keinen Docker-Socket und keine Compose-Dateien. Er hat keinen veröffentlichten Port, akzeptiert nur
das gemeinsame `UPDATE_AGENT_TOKEN` und darf nicht in ein öffentlich erreichbares Netzwerk gelegt werden.

Der Portainer API-Key gehört einem dedizierten technischen Benutzer oder Service-Account. Er benötigt nur Zugriff auf
die Ziel-Environment und Rechte zum Lesen, Aktualisieren und Redeployen genau dieses Ziel-Stacks. Registry-Pull-Rechte
sind nur nötig, falls Portainer sie für den Redeploy des Stacks verlangt. Nicht erforderlich und nicht zu vergeben sind
Admin-Rechte, User-/Team-Verwaltung sowie Zugriff auf andere Environments oder Stacks.

GHCR ist für dieses Projekt öffentlich lesbar. `GHCR_TOKEN` bleibt leer und wird erst benötigt, falls das Image später
privat wird.

## Manuelle Wartung

```bash
docker compose logs --tail=200 app updater db
docker compose exec -T db sh -c 'pg_dump --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > backups/manual-backup.sql.gz
docker compose pull
docker compose up -d
```
