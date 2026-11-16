# Verwaltungsoberflächen: Vorher und Nachher

Vergleich mit `main` / `61f24e0262527287e1c9e35591846dc30291e3db`.
Die Vergleichsansichten verwenden dasselbe synthetische Lager: 210 EUR Soll,
125 EUR bezahlt und 85 EUR offen. Es wurden keine Produktionsdaten verwendet.

| Ansicht | Vorher | Nachher |
| --- | --- | --- |
| Lagerübersicht, 1280 × 900, hell | [Bild](before-camp-desktop.png) | [Bild](after-camp-desktop.png) |
| Lagerübersicht, 390 × 844, hell | [Bild](before-camp-mobile.png) | [Bild](after-camp-mobile.png) |
| Django-Admin, 1280 × 900, dunkel | [Bild](before-django-desktop.png) | [Bild](after-django-desktop.png) |

Die Lageraufgaben sind nach Bereich gruppiert. Globale Verwaltungs- und
Kontofunktionen stehen auf schmalen Bildschirmen in einem nativen Menü.
Teilnehmerdetails besitzen Abschnittslinks; zusätzliche Teilnehmeraktionen
stehen im Menü „Weitere Aktionen“. Menüs und Tabellen bleiben ohne JavaScript
bedienbar. Das technische Admin-Dashboard zeigt Titel und Modellübersicht in der
richtigen Reihenfolge und folgt im automatischen Modus dem Systemfarbschema.

## Komponentenansichten mit synthetischen Daten

Diese Ausschnitte zeigen längere Namen, Registrierungs- und Ausgabenaktionen,
Abrechnungstabellen und native Kostendialoge. Sie verwenden zusätzliche,
ausschließlich synthetische Einträge.

- [Lagerübersicht mit Daten](after-camp-overview-top-populated.png)
- [Registrierungsanfrage prüfen](after-pending-registration-review.png)
- [Ausstehende Gemeinschaftsausgaben](after-pending-expenses-review.png)
- [Genehmigte Gemeinschaftsausgaben](after-approved-expenses-review.png)
- [Teilnehmerabrechnungen](after-settlement-table-review.png)
- [Kostenstellendetails im Dialog](after-cost-center-dialog-review.png)
- [Technische Administration im automatischen Dunkelmodus](after-technical-admin-auto-dark.png)

Die responsive Abnahme prüft 320, 390, 768, 1024, 1128, 1280, 1440 und 1920
Pixel. Playwright deckt zusätzlich lange Tabelleninhalte, 200 % Textgröße,
Reduced Motion, Tastaturbedienung, automatische helle und dunkle Themes sowie
die Navigation und Tabellenbedienung ohne JavaScript ab. Die gezielten
Testergebnisse stehen im Pull Request.

## Vollständige Abnahme am 16. November 2026

2.282 Python- und Migrationstests bestanden, 19 übersprungen. Der vollständige
serielle Browserlauf bestand mit 380 erfolgreichen Prüfungen und einem Skip
in Chromium, Firefox und WebKit. Ruff, Django, Migrationsabgleich und mypy
sind ebenfalls erfolgreich. Die Navigationswechsel sind zusätzlich an den
Grenzen 900/901 und 1100/1101 Pixel abgesichert. Lokal wurde kein Docker genutzt.
