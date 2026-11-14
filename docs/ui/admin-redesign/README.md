# Verwaltungsoberflächen: Vorher und Nachher

Vergleich mit `main` / `61f24e0262527287e1c9e35591846dc30291e3db`.
Alle Aufnahmen verwenden dieselben ausschließlich synthetischen Lager- und
Teilnehmerdaten: 210 EUR Soll, 125 EUR bezahlt und 85 EUR offen.
Es wurden keine Produktionsdaten verwendet.

| Ansicht | Vorher | Nachher |
| --- | --- | --- |
| Lagerübersicht, 1280 × 900, hell | [Bild](before-camp-desktop.png) | [Bild](after-camp-desktop.png) |
| Lagerübersicht, 390 × 844, hell | [Bild](before-camp-mobile.png) | [Bild](after-camp-mobile.png) |
| Django-Admin, 1280 × 900, dunkel | [Bild](before-django-desktop.png) | [Bild](after-django-desktop.png) |

Die Lageraufgaben sind nach Bereich gruppiert. Globale Verwaltungs- und
Kontofunktionen stehen auf schmalen Bildschirmen in einem separaten nativen Menü.
Teilnehmerdetails besitzen Abschnittslinks; zusätzliche Teilnehmeraktionen
stehen im Menü „Weitere Aktionen“. Beide Menüs bleiben ohne JavaScript bedienbar.
Die technische Administration verwendet weiterhin Djangos native Theme-Steuerung.

Die visuelle Abnahme umfasst außerdem Teilnehmerdetails, Django-Listen und
Django-Formulare bei 390, 1280 und 1440 Pixeln in hell und dunkel.
Die automatisierten Prüfungen decken unter anderem Tastaturbedienung,
Rollenrechte, Formularfehler, Tabellenbedienung, Überlauf, die Abläufe ohne
JavaScript und PWA-Cache-Aktualisierung ab. Maßgeblich für ihren Erfolg sind die
im Pull Request dokumentierten Testergebnisse.
