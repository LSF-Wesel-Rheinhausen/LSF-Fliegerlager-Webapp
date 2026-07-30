# Formula-Injection in Kostenstellen-XLSX schließen (Issue #233, M-4 Restlücke)

## Zusammenfassung

- **M-4 (XLSX Formula Injection – verbleibende Lücke):** PR #250 hat die Formel-Maskierung (`safe_csv_row`) nur auf die Abrechnungs- und Teilnehmer-Blätter angewendet. Das Kostenstellen-Blatt (`_write_cost_center_sheet_from_snapshot` in `src/billing/exporters.py`) schrieb seine Zeilen weiterhin ungemaskiert über `sheet.append([...])`.
- Dadurch landeten angreiferkontrollierte Werte – insbesondere die frei eingebbare **Auslagen-Beschreibung** (`expense.description`) sowie **Teilnehmer- und Antragstellernamen** (`participant.full_name`) – als aktive Formeln in den XLSX-Exporten (`camp_workbook_response`, `settlement_run_workbook_bytes`). Beim Öffnen der Datei durch eine Lagerleitung konnten so z. B. `=HYPERLINK(...)`/`=WEBSERVICE(...)`-Payloads ausgeführt werden.
- **Fix:** Alle Datenzeilen des Kostenstellen-Blatts werden jetzt über `safe_csv_row` geschrieben, konsistent mit dem in PR #250 etablierten Muster für die übrigen Blätter. Numerische Zellen (`_decimal_text(...)`, Zähler) bleiben unverändert, da `safe_csv_cell` nur String-Werte mit Formel-Präfix maskiert.

## Geänderte Dateien

- `src/billing/exporters.py`
- `tests/test_audit_findings_233.py`

## Tests

- Neuer, zellinspizierender Regressionstest `test_cost_center_sheet_escapes_formula_cells`: prüft, dass nach `_write_cost_center_sheet_from_snapshot` keine String-Zelle mit `=`, `+`, `-` oder `@` beginnt. Der Test schlägt ohne den Fix nachweislich fehl.
- `tests/test_audit_findings_233.py` und `tests/test_exporters.py` (44 Tests) bestehen, `ruff check`, `ruff format --check` und `mypy src/billing/exporters.py` sind sauber.
