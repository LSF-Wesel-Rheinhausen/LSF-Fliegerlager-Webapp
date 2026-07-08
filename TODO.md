# Aktuelle TODOs

*Die Meilensteine "Dienstpläne & Kiosk-Erweiterungen" sowie "Stabilisierung der E2E-Tests" (Behebung aller Playwright-Flakiness & Zombie-Prozesse) sind erfolgreich abgeschlossen.*

- [ ] Security: CSV Injection in `src/billing/exporters.py` verhindern (Formel-Zeichen wie `=`, `+`, `-`, `@` am Anfang von Strings escapen, z.B. mit vorangestelltem `'`).
- [ ] Security: Race Condition in `src/billing/services.py::approve_shared_expense` beheben. (Verwendung von `select_for_update()` beim Laden des `Expense`-Objekts, um `IntegrityError` bei gleichzeitigen Klicks auf "Genehmigen" zu vermeiden).

Alle aktuellen Phasen sind abgeschlossen.
