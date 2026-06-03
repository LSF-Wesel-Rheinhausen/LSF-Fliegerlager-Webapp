# Stabilisierung der Test-Suite und Erweiterung der Coverage

- **E2E-Tests:** Vollständige Stabilisierung und Parallelisierung der Playwright E2E-Tests durch isolierte SQLite-Datenbanken (`/tmp/e2e_${INDEX}.sqlite3`). Behebung von Timing- und Locator-Fehlern in Kiosk- und Import-Flows.
- **Backend-Tests:** Massive Erweiterung der Test-Coverage in der Businesslogik (`src/billing/`) auf 89%. Alle Kern-Flows in Importern, Exportern, Forms, Services und Modellen sind abgedeckt.
- **CI/CD:** Anpassung der Abhängigkeiten (`pytest-cov` hinzugefügt) und Konfiguration (`pytest.ini`).
