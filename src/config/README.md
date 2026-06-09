# `src/config`

Django-Projektkonfiguration.

Die aktuell unterstützte Laufzeit ist Python 3.13 mit Django 5.2. Authentifizierung akzeptiert E-Mail-Adresse oder Benutzername; anwendungsspezifische Nutzerdaten liegen im separaten `UserProfile` der Billing-App.

- `settings.py`: Apps, Middleware, Datenbank, Auth-Backends, Static-/Media-Dateien und Login-Redirects.
- `urls.py`: Projektweites Routing fuer Admin, Login, Logout und die Billing-App.
- `asgi.py` und `wsgi.py`: Deployment-Einstiege fuer ASGI/WSGI-Server.

Lokale Entwicklung nutzt standardmaessig `DJANGO_DEBUG=1`, damit `runserver` statische Dateien ausliefert. Deployment sollte `DJANGO_DEBUG=0` setzen.

Unterstuetzte Umgebungsvariablen:

- `DJANGO_SECRET_KEY`: Django Secret Key; bei `DJANGO_DEBUG=0` sind mindestens 50 Zeichen Pflicht.
- `DJANGO_DEBUG`: `1` aktiviert Debug-Modus, jeder andere Wert deaktiviert ihn.
- `DJANGO_ALLOWED_HOSTS`: kommaseparierte Hostliste; bei `DJANGO_DEBUG=0` ist ein Wert Pflicht.
- `DJANGO_HTTPS`: `1` aktiviert HTTPS-Redirect sowie sichere Session- und CSRF-Cookies.
- `DJANGO_TRUST_PROXY_SSL_HEADER`: nur auf `1` setzen, wenn ein kontrollierter Reverse Proxy `X-Forwarded-Proto` bereinigt und setzt.
- `DJANGO_HSTS_SECONDS`: HSTS-Dauer; erst nach erfolgreichem HTTPS-Betrieb schrittweise von `0` erhoehen.
- `DJANGO_HSTS_INCLUDE_SUBDOMAINS` und `DJANGO_HSTS_PRELOAD`: nur nach separater Pruefung aktivieren.
- `CSRF_TRUSTED_ORIGINS`: kommaseparierte Origins inklusive Schema.
- `DATABASE_URL`: Datenbank-URL via `dj-database-url`; ohne Wert wird `src/db.sqlite3` genutzt.
