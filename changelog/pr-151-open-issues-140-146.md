## Security-, SSO- und Kiosk-Verbesserungen

- WhiteNoise liefert statische Dateien ohne pauschalen Wildcard-CORS-Header aus; die bestehenden Same-Origin-Schutzheader bleiben erhalten.
- Optionales Authelia Trusted-Header-SSO meldet eindeutige aktive Django-Konten per E-Mail an, ohne Konten oder Rollen zu uebernehmen.
- Ein persistenter Dark-/Light-Mode-Schalter beruecksichtigt beim ersten Aufruf die Systemeinstellung und steht im Admin- sowie Kiosk-Layout bereit (#150).
- Der Kiosk-Login startet mit einem leeren Pflicht-Platzhalter und sortiert Teilnehmer sowie Begleitpersonen nach Nachname (#146).
- Der Abendessendialog bucht mehrere Lagertage und Personen atomar, zeigt bestehende Buchungen sowie Sperrgruende und fuehrt danach zum aktualisierten Kalender zurueck (#143, #144).
- Fruehstueck und Snacks bleiben taggleiche Schnellbuchungen ohne Kalenderauswahl; nur Abendessen verwendet den Lagertagskalender (#143).
- Letzte Schnellbuchungen sind als responsive Liste ohne horizontales Scrollen aufgebaut und werden ueber einen eindeutigen Bestaetigungsdialog storniert (#145).
