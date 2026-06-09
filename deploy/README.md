# Einfaches Docker-Deployment

Für den Deployment-Host werden nur Docker Engine mit Compose V2 und Zugriff auf GHCR benötigt. Das Repository muss
nicht geklont werden; die beiden Beispieldateien können in ein leeres Verzeichnis übernommen werden.

```bash
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
mkdir -p backups docker-config
chmod 700 docker-config
```

In `.env` müssen mindestens `DJANGO_SECRET_KEY`, `UPDATE_AGENT_TOKEN`, `POSTGRES_PASSWORD`, `DATABASE_URL`,
`DJANGO_ALLOWED_HOSTS` und `CSRF_TRUSTED_ORIGINS` angepasst werden. `POSTGRES_PASSWORD` und das Passwort innerhalb
von `DATABASE_URL` müssen identisch sein.

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
Updater erstellt zuerst ein Backup unter `BACKUP_DIR`, startet ausschließlich den App-Service neu und wartet auf dessen
Healthcheck. Schlägt der Start fehl, wird das vorherige Image wieder gestartet. Datenbankmigrationen werden nicht
automatisch zurückgerollt; das erzeugte Backup bleibt für eine kontrollierte Wiederherstellung erhalten.

Der Updater besitzt Zugriff auf `/var/run/docker.sock` und ist deshalb hochprivilegiert. Er hat keinen veröffentlichten
Port, akzeptiert nur das gemeinsame `UPDATE_AGENT_TOKEN` und darf nicht in ein öffentlich erreichbares Netzwerk gelegt
werden.

## Manuelle Wartung

```bash
docker compose logs --tail=200 app updater db
docker compose exec -T db sh -c 'pg_dump --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > backups/manual-backup.sql.gz
docker compose pull
docker compose up -d
```

Für private GHCR-Pakete wird die Anmeldung in das nur für den Updater eingebundene Konfigurationsverzeichnis geschrieben:

```bash
docker --config ./docker-config login ghcr.io
```
