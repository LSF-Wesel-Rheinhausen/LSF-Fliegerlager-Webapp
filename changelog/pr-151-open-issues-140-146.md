## Security-, SSO- und Kiosk-Verbesserungen

- WhiteNoise liefert statische Dateien ohne pauschalen Wildcard-CORS-Header aus; die bestehenden Same-Origin-Schutzheader bleiben erhalten.
- Optionales Authelia Trusted-Header-SSO meldet eindeutige aktive Django-Konten per E-Mail an, ohne Konten oder Rollen zu uebernehmen.
- Ein persistenter Dark-/Light-Mode-Schalter beruecksichtigt beim ersten Aufruf die Systemeinstellung und steht im Admin- sowie Kiosk-Layout bereit (#150).
- Der Kiosk-Login startet mit einem leeren Pflicht-Platzhalter und sortiert Teilnehmer sowie Begleitpersonen nach Nachname (#146).
