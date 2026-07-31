# Login Rate Limiting

- Ergänzt ein anwendungsseitiges Dual-Bucket-Rate-Limiting (IP-Adresse und Username/E-Mail) für den Standard-Web-Login (`FirstLaunchLoginView`), um Brute-Force-Angriffe abzufangen.
- Fügt umfassende Unittests und einen Playwright-E2E-Browser-Test hinzu.
- Ergänzt Dokumentation zu Fail2ban und Reverse Proxy Rate-Limiting in `deploy/README.md`.
