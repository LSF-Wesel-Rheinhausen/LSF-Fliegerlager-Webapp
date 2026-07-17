# `src/config`

Django-Projektkonfiguration.

Die aktuell unterstützte Laufzeit ist Python 3.13 mit Django 5.2. Authentifizierung akzeptiert E-Mail-Adresse oder Benutzername; anwendungsspezifische Nutzerdaten liegen im separaten `UserProfile` der Billing-App.

- `settings.py`: Apps, Middleware, Datenbank, Auth-Backends, Static-/Media-Dateien und Login-Redirects.
- `urls.py`: Projektweites Routing fuer Healthcheck, Admin, Login, Logout und die Billing-App.
- `asgi.py` und `wsgi.py`: Deployment-Einstiege fuer ASGI/WSGI-Server.

Lokale Entwicklung nutzt standardmaessig `DJANGO_DEBUG=1`, damit `runserver` statische Dateien ausliefert. Deployment sollte `DJANGO_DEBUG=0` setzen.

Unterstuetzte Umgebungsvariablen:

- `DJANGO_SECRET_KEY`: Django Secret Key; bei `DJANGO_DEBUG=0` sind mindestens 50 Zeichen Pflicht.
- `DJANGO_DEBUG`: `1` aktiviert Debug-Modus, jeder andere Wert deaktiviert ihn.
- `DJANGO_ALLOWED_HOSTS`: kommaseparierte Hostliste; bei `DJANGO_DEBUG=0` ist ein Wert Pflicht.
- `DJANGO_HTTPS`: `1` aktiviert HTTPS-Redirect sowie sichere Session- und CSRF-Cookies.
- `DJANGO_TRUST_PROXY_SSL_HEADER`: nur auf `1` setzen, wenn ein kontrollierter Reverse Proxy `X-Forwarded-Proto` bereinigt und setzt.
- `AUTHELIA_SSO_ENABLED`: `1` aktiviert Trusted-Header-SSO fuer bereits bestehende aktive Django-Konten; Default `0`.
- `AUTHELIA_SSO_EMAIL_HEADER`: vom kontrollierten Proxy gesetzter E-Mail-Header; Default `Remote-Email`.
- `DJANGO_HSTS_SECONDS`: HSTS-Dauer; erst nach erfolgreichem HTTPS-Betrieb schrittweise von `0` erhoehen.
- `DJANGO_HSTS_INCLUDE_SUBDOMAINS` und `DJANGO_HSTS_PRELOAD`: nur nach separater Pruefung aktivieren.
- `CSRF_TRUSTED_ORIGINS`: kommaseparierte Origins inklusive Schema.
- `DATABASE_URL`: Datenbank-URL via `dj-database-url`; ohne Wert wird `src/db.sqlite3` genutzt.
- `UPDATE_AGENT_URL` und `UPDATE_AGENT_TOKEN`: interne, nur für Superuser-Aktionen verwendete Update-Agent-Verbindung.
- `BACKUP_DIR`: gemeinsames Backup-Verzeichnis im Container; Compose setzt für App, Scheduler und Updater `/backups`.
- `DAILY_SETTLEMENT_BACKUP_INTERVAL_SECONDS`: Prüfintervall des Scheduler-Containers; Default `300`.
- `APP_VERSION`, `APP_REVISION`, `APP_BUILD_DATE` und `APP_CHANGE`: vom Container-Build gesetzte Versionsmetadaten.

WhiteNoise liefert die durch `collectstatic` erzeugten Dateien direkt über Gunicorn aus. Der Update-Agent bleibt ein
separater Container; der Django-Prozess erhält keinen Zugriff auf Portainer-Zugangsdaten.

Trusted-Header-SSO vertraut einem unsignierten internen Header. Bei Aktivierung darf die App deshalb nicht direkt
erreichbar sein. Der Reverse Proxy muss eingehende Identitaetsheader entfernen und `Remote-Email` ausschliesslich aus
Authelias Forward-Auth-Antwort neu setzen. Die Anwendung ordnet diese E-Mail case-insensitiv genau einem vorhandenen,
aktiven Benutzer zu. Sie erstellt keine Konten und uebernimmt weder `Remote-Groups` noch andere Authelia-Rollen.

`GET /healthz/` prüft die Anwendungs- und Datenbankbereitschaft. Der Endpunkt liefert ausschließlich `{"status":"ok"}` oder bei Datenbankfehlern `{"status":"unavailable"}`.
