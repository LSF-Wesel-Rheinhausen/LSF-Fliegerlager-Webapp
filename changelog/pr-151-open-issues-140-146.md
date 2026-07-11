## Security-, SSO- und Kiosk-Verbesserungen

- WhiteNoise liefert statische Dateien ohne pauschalen Wildcard-CORS-Header aus; die bestehenden Same-Origin-Schutzheader bleiben erhalten.
- Optionales Authelia Trusted-Header-SSO meldet eindeutige aktive Django-Konten per E-Mail an, ohne Konten oder Rollen zu uebernehmen.
