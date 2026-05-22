# `src/config`

Django-Projektkonfiguration.

- `settings.py`: Apps, Middleware, Datenbank, Auth-Backends, Static-/Media-Dateien und Login-Redirects.
- `urls.py`: Projektweites Routing fuer Admin, Login, Logout und die Billing-App.
- `asgi.py` und `wsgi.py`: Deployment-Einstiege fuer ASGI/WSGI-Server.

Lokale Entwicklung nutzt standardmaessig `DJANGO_DEBUG=1`, damit `runserver` statische Dateien ausliefert. Deployment sollte `DJANGO_DEBUG=0` setzen.
