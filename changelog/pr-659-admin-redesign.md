# Admin-Oberflächen

- Die Lagerübersicht fasst Abrechnungs- und Zahlungskennzahlen getrennt zusammen. Exporte und Bereichsaktionen verwenden einheitliche Schaltflächen; Tabellen bleiben in beschrifteten, per Tastatur horizontal scrollbaren Ansichten bedienbar.
- Registrierungs- und Gemeinschaftsausgaben, Teilnehmerabrechnungen, Preisregeln und Kostenstellendetails folgen einer gemeinsamen Tabellen-, Formular- und Dialoggestaltung. Fehler bei der Freigabe werden direkt am Formular angezeigt.
- Das technische Django-Dashboard nutzt die verfügbare Breite, zeigt seinen Titel vor den Modellen und übernimmt auch im automatischen Modus die System-Farbschemaeinstellung.
- Der gemeinsame Tabellenwerkzeug-Helper setzt Filter- und Sortierfelder außerhalb des horizontal scrollenden Tabellenbereichs. Der PWA-Cache wurde für die aktualisierten Verwaltungsassets angehoben.
- Gezielte Prüfung: Django-Systemcheck ohne Befund; Pytest `test_admin_redesign.py` und `test_pwa.py` (28 bestanden); zehn Chromium-Playwright-Tests zu Neugestaltung und Tabellenwerkzeugen sowie vier Chromium-Abläufe zu Setup, Export-Touchzielen, mobiler Kopfzeile und dunklem Theme bestanden.
- Responsive Playwright-Prüfungen: 320, 390, 768, 1024, 1280, 1440 und 1920 Pixel; lange Registrierungsdaten bei 320, 390, 768, 1128 und 1440 Pixeln; zusätzlich 200 % Textgröße, Reduced Motion und Navigation ohne JavaScript.

- Vollständige Abnahme: 2.282 Python- und Migrationstests bestanden, 19 übersprungen; 380 Browserprüfungen in Chromium, Firefox und WebKit bestanden, eine übersprungen. Ruff, Django, Migrationsabgleich und mypy sind erfolgreich.
