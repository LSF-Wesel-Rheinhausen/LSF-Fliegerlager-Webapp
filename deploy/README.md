# Portainer-Deployment

Für den Deployment-Host werden Portainer Business Edition, Docker Engine und Zugriff auf GHCR benötigt. Das Repository
muss nicht geklont werden; die beiden Beispieldateien können in einen Portainer-Stack übernommen werden.

```bash
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
mkdir -p /srv/fliegerlager
```

In `.env` müssen mindestens `DJANGO_SECRET_KEY`, `UPDATE_AGENT_TOKEN`, `UPDATE_AGENT_URL`, `POSTGRES_PASSWORD`,
`DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `PORTAINER_URL`, `PORTAINER_API_KEY`,
`PORTAINER_ENDPOINT_ID` und `PORTAINER_STACK_ID` angepasst werden. `POSTGRES_PASSWORD` und das Passwort innerhalb von
`DATABASE_URL` müssen identisch sein.

Pflichtvariablen für den Update-Agent:

- `UPDATE_AGENT_TOKEN`: internes Bearer-Token zwischen Django und Updater.
- `UPDATE_AGENT_URL`: interne Django-Adresse des Updaters; im Compose-Beispiel `http://updater:8080`.
- `APP_IMAGE`: Ziel-Image als Portainer-Stack-Variable für den `app`-Service; diese Variable darf nicht an den
  `updater`-Service übergeben werden.
- `DATABASE_URL`: PostgreSQL-Verbindung für `pg_dump`-Backups.
- `PORTAINER_URL`: Portainer-Basis-URL, zum Beispiel `https://portainer.example.org` oder `https://host:9443`.
- `PORTAINER_API_KEY`: API-Key eines dedizierten technischen Portainer-Benutzers.
- `PORTAINER_ENDPOINT_ID`: Portainer Environment/Endpoint-ID des Ziel-Stacks.
- `PORTAINER_STACK_ID`: Portainer Stack-ID des Ziel-Stacks.

## Service-spezifische Umgebungsvariablen

Die Compose-Dateien injizieren `.env` nicht mehr pauschal in alle Container. Jeder Dienst erhält nur die für seinen
Prozess benötigten Variablen:

- `app`: Django-/Datenbankkonfiguration, Update-Agent-Token und -URL, Web-Push-Konfiguration sowie
  Anwendungsoptionen. Portainer- und Registry-Zugangsdaten werden nicht an die App übergeben.
- `daily-settlement-backup`: Django-Secret, Django-Host-Allowlist, Datenbank-URL, Backup-Pfad und Backup-Intervall.
- `push-worker`: Django-Secret, Django-Host-Allowlist, Datenbank-URL, Web-Push-Schlüssel/-Subject, die erlaubten
  Push-Origins und das Worker-Intervall.
- `email-worker`: Django-Secret, Django-Host-Allowlist und Datenbank-URL. SMTP-Zugangsdaten liegen verschlüsselt in
  PostgreSQL; Web-Push-Schlüssel werden diesem Dienst nicht bereitgestellt.
- `updater`: Update-Agent-Token, Datenbank-/Backup-Konfiguration, Portainer-Zugangsdaten, Registry-Allowlist und
  optional `GHCR_TOKEN`.

`PORTAINER_URL`, `PORTAINER_API_KEY`, `PORTAINER_ENDPOINT_ID`, `PORTAINER_STACK_ID` und `GHCR_TOKEN` dürfen nur im
`updater`-Service vorkommen. Änderungen an der Allowlist müssen durch die Compose-Konfigurationstests abgesichert
werden.

`DJANGO_ALLOWED_HOSTS` wird für den `app`-Service weiterhin zwingend aus `.env` verlangt. Die drei Worker verwenden
dieselbe Variable und fallen bei einem isolierten Start sicher auf `localhost,127.0.0.1` zurück; eine Wildcard wird
nicht verwendet.

Optionale Variablen mit Defaults:

- `UPDATER_IMAGE`: Updater-Container-Image; Default ist das veröffentlichte GHCR-Updater-Image.
- `UPDATE_HEALTH_TIMEOUT`: maximale Wartezeit auf `APP_HEALTH_URL` in Sekunden; Default `180`.
- `DAILY_SETTLEMENT_BACKUP_INTERVAL_SECONDS`: Prüfintervall des Scheduler-Containers; Default `300`.
- `WEB_PUSH_WORKER_INTERVAL_SECONDS`: Prüfintervall des Push-Workers; Default `60`.
- `APP_HEALTH_URL`: Healthcheck-URL der App; Default `http://app:8000/healthz/`.
- `TARGET_SERVICE`: Compose-Service des App-Containers für Rollback-Digest-Ermittlung; Default `app`.
- `MAX_AGENT_BODY_BYTES`: maximales JSON-Request-Body-Limit des Update-Agents; Default `1048576` Bytes.
- `AGENT_READ_TIMEOUT_SECONDS`: maximale Lesedauer für einen Request-Body; Default `10` Sekunden.
- `MAX_AGENT_CONCURRENT_REQUESTS`: maximale Zahl paralleler Update-Agent-Requests; Default `8`.
- `PERSISTENCE_DIR`: absoluter Host-Pfad für alle persistenten Daten; für Portainer wird `/srv/fliegerlager` empfohlen.
- `BACKUP_DIR`: bisheriger Host-Pfad der Backups; dient nur als Quelle bei der einmaligen Speichermigration.
- `PORTAINER_VERIFY_SSL`: Portainer-Zertifikatsprüfung; Default `true`. Für interne Portainer-Instanzen mit Self-Signed-Zertifikat `false` setzen.
- `GHCR_TOKEN`: nur für private GHCR-Images setzen; bei öffentlichen Images leer lassen.
- `UPDATE_REGISTRY_ALLOWED_HOSTS`: komma-separierte Liste exakter Registry-Hosts mit optionalem Port; Default
  `ghcr.io`. Erlaubt sind ausschließlich `Host[:Port]` ohne Schema, Pfad, Userinfo, Wildcards oder abschließenden
  Punkt. Benutzerdefinierte Registries müssen hier explizit eingetragen werden, zum Beispiel
  `ghcr.io,registry.example.org:5443`.
- `TZ`: Zeitzone des Updaters; Default `Europe/Berlin`.

Der Compose-Service `storage-migrate` legt die Zielstruktur an und setzt die schreibbaren App-Verzeichnisse auf
UID/GID `10001:10001`. Danach verwenden alle Container denselben Host-Ordner:

```text
/srv/fliegerlager/
  postgres/
  media/
  backups/
  updater-state/
  secrets/webpush/
  migration/
```

## Einmalige Migration bestehender Installationen

Die erste Bereitstellung dieser Compose-Version benötigt ein Wartungsfenster. PostgreSQL-Dateien dürfen nicht kopiert
werden, während die bisherige Datenbank läuft.

1. Vorhandenen Stack in Portainer stoppen, aber weder Stack noch Volumes löschen.
2. Im Stack `PERSISTENCE_DIR=/srv/fliegerlager` setzen. `BACKUP_DIR` muss weiterhin auf den bisherigen Backup-Pfad zeigen.
3. Die Compose-Datei dieser Version in den Stack übernehmen und den Stack neu bereitstellen.
4. In den Logs von `storage-migrate` auf `Persistence migration completed` prüfen. Erst danach starten Datenbank und App.
5. App-Healthcheck, Medien und vorhandene Abrechnungen prüfen.

Die Migration liest die drei bisherigen Named Volumes und `BACKUP_DIR`, kopiert deren Inhalt in die neue Struktur und
schreibt anschließend `migration/v1.json`. Wiederholte Starts erkennen diese Markierung und kopieren nichts erneut.
Ein `postmaster.pid`, eine inkompatible PostgreSQL-Version oder bereits vorhandene unbekannte Zieldaten führen zum
Abbruch. `PERSISTENCE_DIR` und `BACKUP_DIR` müssen verschiedene Host-Pfade sein. Die alten Volumes werden nie verändert
oder gelöscht und bleiben als Rückfalloption erhalten. Ein Rückfall
auf die alte Compose-Datei enthält allerdings keine Datenänderungen, die erst nach der Migration entstanden sind.

```bash
docker compose pull
docker compose up -d
docker compose ps
curl http://127.0.0.1:8000/healthz/
```

Standardmäßig bindet die App nur an `127.0.0.1:8000`, passend für einen Reverse Proxy auf demselben Host. Für einen
direkten Zugriff im lokalen Netz kann `APP_BIND_ADDRESS=0.0.0.0` gesetzt werden. Bei HTTPS hinter einem kontrollierten
Proxy bleiben `DJANGO_HTTPS=1` und `DJANGO_TRUST_PROXY_SSL_HEADER=1` aktiv.

Damit fehlgeschlagene Lager-PIN-Eingaben pro Kiosk statt gemeinsam für alle Proxy-Clients begrenzt werden, muss
`KIOSK_ACCESS_TRUSTED_PROXY_ADDRESSES` die kommaseparierten, exakten Quell-IP-Adressen der direkten Proxys enthalten.
Maßgeblich ist die im App-Container als `REMOTE_ADDR` sichtbare Adresse; sie kann bei Docker von `127.0.0.1` abweichen.
Ohne diese Einstellung ignoriert Django `X-Forwarded-For`. Jeder eingetragene Proxy muss einen eingehenden
`X-Forwarded-For`-Header entfernen und ihn mit genau einer tatsächlichen Client-IP ersetzen, beispielsweise in Nginx:

```nginx
proxy_set_header X-Forwarded-For $remote_addr;
```

Angehängte Weiterleitungsketten wie bei `$proxy_add_x_forwarded_for` werden absichtlich nicht vertraut. Der App-Port
darf für Clients nicht unter Umgehung des konfigurierten Proxys erreichbar sein.

### Rate Limiting & Härtung für Go-Live (Fail2ban / Reverse Proxy)

Die Anwendung schützt Logins (Standard-Login & Kiosk-PIN) anwendungsseitig vor Brute-Force-Angriffen (Sperre nach 5 Fehlversuchen für 5 Minuten). Für den produktiven Einsatz im öffentlichen Internet wird eine ergänzende Härtung auf Infrastruktur-Ebene empfohlen:

- **Reverse Proxy Rate Limiting (Nginx / Traefik):** Richte auf dem Reverse Proxy ein Zonen-Rate-Limiting für `/login/` ein (z. B. `limit_req_zone` in Nginx), um automatisierte Bot-Anfragen direkt am Proxy abzufangen, bevor sie Python-Worker belasten.
- **Fail2ban (Host-Ebene):** Auf dem Deployment-Host kann `fail2ban` installiert werden, um die Access-Logs des Reverse Proxys auf wiederholte HTTP 429/401-Fehler zu überwachen und angreifende Client-IPs direkt per Linux-Firewall (`iptables`/`nftables`) zu sperren.

## Authelia Trusted-Header-SSO

Optional kann Authelia bereits vorhandene Django-Benutzer ueber deren eindeutige E-Mail-Adresse anmelden:

```dotenv
AUTHELIA_SSO_ENABLED=1
AUTHELIA_SSO_EMAIL_HEADER=Remote-Email
```

Der Header ist nicht signiert und darf nur innerhalb der kontrollierten Proxy-Verbindung verwendet werden. Vor der
Aktivierung gelten deshalb alle folgenden Anforderungen:

- Port `8000` darf fuer Clients nicht direkt erreichbar sein; `APP_BIND_ADDRESS=127.0.0.1` beibehalten oder den Zugriff
  gleichwertig per Firewall beziehungsweise privatem Proxy-Netz sperren.
- Der Reverse Proxy entfernt jeden vom Client gesendeten `Remote-Email`-Header und setzt ihn ausschliesslich aus
  Authelias Forward-Auth-Antwort neu. Weitere Identitaetsheader wie `Remote-Groups` werden nicht an Django uebernommen.
- Bei einem Proxy-Container ist nur dessen feste Quell-IP zu vertrauen. Ein komplettes gemeinsam genutztes Docker-Netz
  ist keine ausreichende Vertrauensgrenze.
- Jede Authelia-E-Mail muss case-insensitiv genau einem aktiven Django-Konto entsprechen. Unbekannte, doppelte,
  ungueltige und inaktive Konten werden mit einer generischen Antwort abgelehnt.

Django legt keine Benutzer an und veraendert weder Gruppen noch `is_staff`/`is_superuser`. Die vorhandenen
Anwendungsrollen bleiben allein fuer die Autorisierung massgeblich. Fehlt der konfigurierte Header, bleibt der
Passwort-Login als Fallback verfuegbar.

## Passkey-/WebAuthn-Anmeldung

Passkeys werden erst nach vollständiger Konfiguration aktiviert:

```dotenv
PASSKEY_ENABLED=1
PASSKEY_RP_ID=app.example.org
PASSKEY_RP_NAME=Fliegerlager-Abrechnung
PASSKEY_ORIGIN=https://app.example.org
```

`PASSKEY_RP_ID` enthält ausschließlich den öffentlichen Domainnamen; IP-Adressen sind nicht zulässig.
`PASSKEY_ORIGIN` muss dem im Browser sichtbaren Origin einschließlich Schema und gegebenenfalls Port exakt
entsprechen. Außerhalb von `localhost` ist HTTPS Pflicht.
Ein späterer Wechsel der RP-ID macht bereits registrierte Credentials unbrauchbar. Deshalb muss vor Domainwechseln
der Passwort- oder Authelia-Fallback geprüft werden. Weitere Sicherheits- und Recovery-Hinweise stehen in
[`../docs/passkeys.md`](../docs/passkeys.md).

## PWA und Web Push

Die PWA funktioniert ohne zusätzliche Konfiguration. Für Push-Benachrichtigungen
`WEB_PUSH_VAPID_PUBLIC_KEY` und `WEB_PUSH_VAPID_PRIVATE_KEY` leer lassen, `WEB_PUSH_VAPID_SUBJECT` auf eine betreute
`mailto:`-Adresse setzen und `WEB_PUSH_ENABLED=1` aktivieren. Beim ersten App-Start wird ein Schlüsselpaar unter
`PERSISTENCE_DIR/secrets/webpush/` erzeugt und bei weiteren Starts wiederverwendet. Bereits explizit konfigurierte
Schlüssel haben weiterhin Vorrang.

Der private Schlüssel darf nicht in Git, Logs oder Screenshots gelangen. Der gesamte persistente Ordner muss in die
Host-Backupstrategie aufgenommen werden. Eine Schlüsselrotation macht bestehende Browser-Subscriptions unbrauchbar;
betroffene Geräte müssen Push danach erneut aktivieren.

`WEB_PUSH_ALLOWED_ORIGINS` ist eine kommaseparierte Liste exakter Origins der tatsächlich eingesetzten Browser-
Pushdienste, zum Beispiel `https://push.example.org` ohne Pfad. Es werden ausschließlich HTTPS, der effektive Port
443, Hostnamen ohne Userinfo/IP-Literal/Platzhalter und eine exakte Origin-Übereinstimmung akzeptiert. Die Liste bleibt
standardmäßig leer (Fail-Closed); der Betreiber muss die in der eigenen Browser-/Push-Service-Konfiguration verwendeten
Origins vor der Aktivierung eintragen. Die Anwendung führt keine DNS-Auflösung als Vertrauensentscheidung durch.
Redirects werden beim Versand nicht verfolgt. Eine restriktive Egress-Regel des Container-/Proxy-Netzes bleibt als
Defense in Depth erforderlich.

Der Service `push-worker` erzeugt terminierte Erinnerungen und verarbeitet die Datenbank-Outbox. Zentrale Tablets
verwenden `/central/kiosk/` und bieten keine Push-Aktivierung an. Weitere Betriebsdetails stehen in
[`../docs/pwa-push.md`](../docs/pwa-push.md).

## Manueller E-Mail-Versand

SMTP-Host, Zugangsdaten, Transportverschlüsselung und Absender werden nicht in `.env`, sondern durch einen Admin unter
**E-Mail** im Webinterface gepflegt. Das SMTP-Passwort liegt verschlüsselt in PostgreSQL; die Schlüsselableitung nutzt
den vorhandenen `DJANGO_SECRET_KEY`. Nach dessen Rotation muss das SMTP-Passwort erneut gespeichert werden.

Der Service `email-worker` verarbeitet ausschließlich Informations- und Rechnungs-E-Mails, die ein Admin nach einer
Empfängervorschau ausdrücklich bestätigt hat. Er benötigt ausgehenden Zugriff auf den konfigurierten SMTP-Server,
veröffentlicht aber keinen Port. Betriebs- und Sicherheitshinweise stehen in
[`../docs/email-delivery.md`](../docs/email-delivery.md).

## Updates

### First Upgrade auf den entkoppelten Updater

Vor dem ersten normalen Update mit dieser Version muss die aktive Stack-Definition kontrolliert aktualisiert werden:

1. Die aktuelle [`docker-compose.example.yml`](docker-compose.example.yml) in Portainer mit der aktiven Definition
   vergleichen und übernehmen. Insbesondere darf `APP_IMAGE` nicht in der Environment des `updater`-Service stehen.
   Dessen Konfiguration muss direkt ausgeschrieben sein: YAML-Aliase, Anchors und Merge-Keys im `updater`-Block vor
   dem Upgrade auflösen; `env_file` und `extends` werden dort ebenfalls nicht akzeptiert.
2. Den Stack neu bereitstellen und warten, bis der `updater`-Container neu gestartet ist.
3. Den Health-Status von `updater` und `app` in Portainer prüfen; beide müssen healthy sein. Zusätzlich darf der
   Updater-Healthcheck intern mit `GET /healthz` geprüft werden.
4. Erst danach den normalen Update-Check (`POST /check`) und anschließend die bestätigte Installation
   (`POST /install`) verwenden.

Ein noch nicht migrierter Altstack wird bewusst vor der Kandidatenerzeugung abgewiesen. Dadurch kann eine Änderung von
`APP_IMAGE` den laufenden Updater beim ersten Upgrade nicht mehr ersetzen oder mit einer neuen Environment starten.

### Recovery nach einem Updater-Neustart

Der Updater startet erst, wenn der `app`-Service healthy ist, und überbrückt vor dem Server-Bind nur transiente
Portainer-Verbindungsfehler mit begrenztem Backoff. Nach einem Neustart mit persistiertem Updatezustand wartet die
Recovery begrenzt auf einen eindeutigen App-Runtime-Digest und den Healthcheck. Ein einmalig fehlender oder mehrfach
sichtbarer App-Container löst deshalb keinen sofortigen Stack-Redeploy aus.

Sind Ziel- und Rollback-Image identisch, wird der Stack nicht automatisch redeployt: Ein healthy verifiziertes Ziel
wird als `complete` mit `target_verified` abgeschlossen. Ohne diesen Nachweis bleibt der Zustand
`recovery_required` und verlangt einen kontrollierten manuellen Eingriff.

Ein Django-Superuser öffnet **Updates**, prüft das bereitgestellte `latest`-Image und bestätigt die Installation. Der
Updater liest die OCI-Metadaten aus GHCR und speichert den dabei validierten `repo@sha256:...`-Digest als freigegebenen
Installationskandidaten. `/install` verwendet ausschließlich diesen gespeicherten Digest und fragt das bewegliche Tag
nicht erneut ab. Vor dem Update ermittelt der Updater den unveränderlichen Digest des laufenden App-Containers,
erstellt ein Backup unter `BACKUP_DIR`, setzt `APP_IMAGE` über die Portainer-API und wartet auf `APP_HEALTH_URL`.
Anschließend wird der tatsächlich laufende RepoDigest erneut gelesen und exakt mit dem freigegebenen Digest verglichen.
Schlägt ein Schritt fehl oder stimmt der Digest nicht überein, setzt der Updater `APP_IMAGE` auf den vorher ermittelten
unveränderlichen Digest zurück und redeployt den Stack erneut. Datenbankmigrationen werden nicht automatisch
zurückgerollt; das erzeugte Backup bleibt für eine kontrollierte Wiederherstellung erhalten.

Der Update-Agent akzeptiert nur Requests mit `Content-Length`, begrenzt den JSON-Body und weist unvollständige oder zu
langsam gelesene Bodies mit generischen Fehlern zurück. Eine feste Semaphore begrenzt die Anzahl paralleler Requests.
Backups teilen sich einen Lock; während eines laufenden Backups antwortet `POST /backup` mit HTTP 409. Archivnamen
enthalten einen kryptografischen Zufallssuffix und werden exklusiv angelegt, sodass auch gleiche Zeitstempel keine
vorhandenen Archive überschreiben.

Der Updater erhält keinen Docker-Socket und keine lokal eingebundenen Compose-Dateien. Die aktive Definition liest er
ausschließlich über den begrenzten Portainer-Stackvertrag. Er hat keinen veröffentlichten Port, akzeptiert nur das
gemeinsame `UPDATE_AGENT_TOKEN` und darf nicht in ein öffentlich erreichbares Netzwerk gelegt werden.

Der Portainer API-Key gehört einem dedizierten technischen Benutzer oder Service-Account. Er benötigt nur Zugriff auf
die Ziel-Environment und Rechte zum Lesen, Aktualisieren und Redeployen genau dieses Ziel-Stacks. Registry-Pull-Rechte
sind nur nötig, falls Portainer sie für den Redeploy des Stacks verlangt. Nicht erforderlich und nicht zu vergeben sind
Admin-Rechte, User-/Team-Verwaltung sowie Zugriff auf andere Environments oder Stacks.

GHCR ist für dieses Projekt öffentlich lesbar. `GHCR_TOKEN` bleibt leer und wird erst benötigt, falls das Image später
privat wird. Der Update-Agent sendet dieses Credential ausschließlich an den exakt validierten Host `ghcr.io`.
Discovery-Requests verwenden nur HTTPS und ausschließlich Hosts aus `UPDATE_REGISTRY_ALLOWED_HOSTS`; private,
reservierte und anderweitig spezielle IP-Literale sowie nicht exakt erlaubte Hosts werden ohne DNS-Vertrauensprüfung
abgewiesen. Registry- und Token-Endpunkte dürfen nicht redirecten, sodass Credentials und Bearer-Tokens den geprüften
Host nicht verlassen.

## Manuelle Wartung

```bash
docker compose logs --tail=200 app updater db
docker compose exec -T db sh -c 'pg_dump --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > backups/manual-backup.sql.gz
docker compose pull
docker compose up -d
```
