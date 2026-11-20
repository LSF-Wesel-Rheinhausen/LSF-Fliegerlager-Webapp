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

## Tabellen auf schmalen Bildschirmen

Registrierungen und Gemeinschaftsausgaben stehen bei schmalen Ansichten als
beschriftete Datensätze untereinander. Teilnehmerabrechnungen behalten ihre
Spalten und lassen sich im eigenen Bereich seitlich scrollen; der Hinweis und
der Tastaturfokus erscheinen nur dann, wenn tatsächlich Überlauf besteht.

| Ansicht | Screenshot |
| --- | --- |
| Lagerübersicht, 320 Pixel | [Übersicht](overview-320.png) |
| Lagerübersicht, 390 Pixel, hell | [Übersicht](overview-390.png) |
| Lagerübersicht, 390 Pixel, dunkel | [Übersicht](overview-390-dark.png) |
| Lagerübersicht, 768 Pixel | [Übersicht](overview-768.png) |
| Lagerübersicht, 1280 Pixel | [Übersicht](overview-1280-final.png) |
| Registrierung, 320 Pixel | [Datensatz und Aktionen](registrations-320.png) |
| Ausstehende Ausgaben, 320 Pixel | [Datensätze und Aktionen](pending-expenses-320.png) |
| Genehmigte Ausgaben, 320 Pixel | [Felder und Kategorie](approved-expenses-320.png) |
| Teilnehmerabrechnungen, 320 Pixel | [Vergleichstabelle mit Scrollhinweis](settlements-320.png) |
| Lagerübersicht, 390 Pixel, 200 % Text | [Erweiterte Schriftgröße](overview-390-200-text.png) |
| Lagerübersicht, 390 Pixel, ohne JavaScript | [HTML-Fallback](overview-390-no-js.png) |

Die responsive Abnahme prüft 320, 390, 768, 1024, 1128, 1280, 1440 und 1920
Pixel. Playwright deckt zusätzlich lange Tabelleninhalte, 200 % Textgröße,
Reduced Motion, Tastaturbedienung, automatische helle und dunkle Themes sowie
die Navigation und Tabellenbedienung ohne JavaScript ab. Die gezielten
Testergebnisse stehen im Pull Request.

## Prüfung der responsiven Tabellen

Das unabhängige Review und die gezielten Nachprüfungen bestanden. Ruff,
Formatierung, Django, Migrationsabgleich und mypy sind erfolgreich.
2.259 Python- und 23 Migrationstests bestanden; 19 wurden übersprungen.
Die gezielten Browserprüfungen decken die mobilen Datensätze, Tabellenköpfe,
Sortierung und Vergleichstabellen in Chromium, Firefox und WebKit ab.

Die CI-Ergebnisse zum aktuellen Commit sind im Pull Request verfügbar.
