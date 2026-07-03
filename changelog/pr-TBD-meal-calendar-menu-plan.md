# Essenskalender & Speiseplanpflege (PR TBD)

Dieses Feature macht den Kiosk-Essensbereich zu einem echten Buchungskalender und ergänzt die Speiseplanpflege in der Essensübersicht.

### Kiosk
- Der Essenskalender zeigt alle Lagertage, auch wenn noch keine Essensanmeldung existiert.
- Tageskarten zeigen Status, Menütext und den für den angemeldeten Teilnehmer gültigen Abendessenpreis.
- Buchbare Tage öffnen direkt den bestehenden Abendessen-Dialog; geschlossene Tage bleiben sichtbar, aber ohne Buchungsaktion.
- Datumsgebundene Spezialpreise gelten nur noch für exakt passende Essensdaten.

### Admin-Interface
- Admins, Bearbeiter und HüBers können Menütexte direkt in der Essensübersicht pro Lagertag pflegen.
- Die Caterer-Zählwerte bleiben neben dem Speiseplan sichtbar.

### Tests
- Django-Tests decken Kalenderdarstellung, Speiseplantext, geschlossene Tage, HüBers-Speicherung und datumsgenaue Preisauflösung ab.
- Die E2E-Suite wurde vollständig gegen Chromium, Firefox und WebKit verifiziert.
