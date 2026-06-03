# `src/config`

Django-Projektkonfiguration.

- `settings.py`: Apps, Middleware, Datenbank, Auth-Backends, Static-/Media-Dateien und Login-Redirects.
- `urls.py`: Projektweites Routing fuer Admin, Login, Logout und die Billing-App.
- `asgi.py` und `wsgi.py`: Deployment-Einstiege fuer ASGI/WSGI-Server.

Lokale Entwicklung nutzt standardmaessig `DJANGO_DEBUG=1`, damit `runserver` statische Dateien ausliefert. Deployment sollte `DJANGO_DEBUG=0` setzen.

Unterstuetzte Umgebungsvariablen:

- `DJANGO_SECRET_KEY`: Django Secret Key; lokal faellt die App auf einen Dev-Platzhalter zurueck.
- `DJANGO_DEBUG`: `1` aktiviert Debug-Modus, jeder andere Wert deaktiviert ihn.
- `DJANGO_ALLOWED_HOSTS`: kommaseparierte Hostliste; ohne Wert ist lokal `*` erlaubt.
- `CSRF_TRUSTED_ORIGINS`: kommaseparierte Origins inklusive Schema.
- `DATABASE_URL`: Datenbank-URL via `dj-database-url`; ohne Wert wird `src/db.sqlite3` genutzt.
