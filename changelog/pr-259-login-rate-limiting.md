# Login Rate Limiting und Security Hardening

- Ergänzt ein anwendungsseitiges Dual-Bucket-Rate-Limiting (IP-Adresse und Username/E-Mail) für den Standard-Web-Login (`FirstLaunchLoginView`), um Brute-Force-Angriffe abzufangen.
- Fügt umfassende Unittests und einen Playwright-E2E-Browser-Test hinzu.
- Ergänzt Dokumentation zu Fail2ban und Reverse Proxy Rate-Limiting in `deploy/README.md`.
- Setzt das Django-App-Image standardmäßig auf Produktionsmodus, sodass fehlende Produktionskonfiguration den Containerstart sicher abbricht.
- Prüft hochgeladene Rechnungsbelege aus App und Django-Admin anhand konsistenter Endungen, MIME-Typen und Dateisignaturen für PDF, JPEG, PNG und HEIC.
- Liefert geschützte Rechnungsbelege ausschließlich als Download-Anhang aus und deckt manipulierte sowie abgeschnittene Dateien durch Regressionstests ab.
