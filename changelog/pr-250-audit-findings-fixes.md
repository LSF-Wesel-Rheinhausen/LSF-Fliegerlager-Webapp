# Behebung der verbleibenden Audit-Befunde (Issue #233)

## Zusammenfassung

- **M-4 (XLSX Formula Injection):** Maskiert Formel-Präfixe (`=`, `+`, `-`, `@`) in allen openpyxl XLSX-Tabellenzeilen per `safe_csv_row`.
- **B-1 & B-2 (Anmeldezeitraum & `booked_nights`):** Revalidiert Datumsangaben in `update_attendance_dates`, schützt vor `ValueError` bei ungültigen Strings, prüft `departure >= arrival` und berechnet `booked_nights` neu inklusive Persistierung in `update_fields`.
- **B-4 (CSP Nonce in Inline-Script):** Bindet das Inline-Script in `shift_manage.html` an den CSP-Nonce (`{% if request.csp_nonce %}nonce="..."{% endif %}`).
- **B-6 (Rollen-Ermittlung):** Gibt in `user_role()` für Konten ohne zugewiesene Gruppen einen leeren String zurück statt fälschlicherweise „Bearbeiter“.
- **B-7 (CSV-Import Status-Validierung):** Validiert die importierte Status-Spalte in `normalize_row` gegen `Participant.Status.choices` (Code & Label) und meldet ungültige Werte als Importfehler.
- **B-8 (Essensbuchungsformular Lagergrenzen):** Erzwingt in `MealBookingForm.clean_meal_dates()` die Validierung ausgewählter Daten gegen `starts_on` und `ends_on` des Lagers.
- **B-9 (Update-Agent Non-ASCII Header):** Wandelt den `Authorization`-Header vor dem `hmac.compare_digest`-Aufruf in `bytes` um, um `TypeError` bei Non-ASCII-Zeichen zu vermeiden.
- **B-10 (Test-Benachrichtigungen Fallback):** Setzt bei Test-Benachrichtigungen für Push-Geräte ohne Kategorien einen sicheren Fallback auf die erste erlaubte Kategorie der jeweiligen Rolle.

## Geänderte Dateien

- `src/billing/exporters.py`
- `src/billing/views.py`
- `src/templates/billing/shift_manage.html`
- `src/billing/roles.py`
- `src/billing/importers.py`
- `src/billing/forms.py`
- `deployment_agent.py`
- `src/billing/notification_views.py`
- `tests/test_audit_findings_233.py`

## Tests

- Automatisierte Regressionstests in `tests/test_audit_findings_233.py` für alle 8 gehärteten Befunde.
- Vollständige pytest-Suite (764/764 Tests bestanden), Django System Check, `ruff` Linting/Formatierung und `mypy src`.
