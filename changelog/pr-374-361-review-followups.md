# PR #374 – Review-Follow-ups zu #361

## Zusammenfassung

- Korrigiert die Validierungsreihenfolge für manuell angelegte Familienkosten.
- Hält abgewiesene Stornos historischer, mehrdeutig zugeordneter Essenskosten atomar unverändert.
- Fordert eine explizite Bestätigung vor abrechnungsrelevanten Rollen-, Aufenthalts- und Statusänderungen an Familienmitgliedern.
- Zeigt im Familien-Kiosk-Audit den unveränderlichen Namens-Snapshot an.

## Geänderte Dateien

- `src/billing/views.py`
- `src/templates/billing/participant_detail.html`
- `src/templates/billing/participant_family_member_edit.html`
- `tests/test_family_billing.py`
- `tests/test_kiosk_partner_access.py`

## Tests

- Gezielte RED/GREEN-Regressionstests für alle vier Review-Findings sowie CSRF-/Invalid-POST-Randfälle.

## Offene Punkte

- Keine.
