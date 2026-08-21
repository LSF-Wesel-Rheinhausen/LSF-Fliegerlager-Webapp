# Auditierbares Löschen von eingetragenen Zahlungen

- Ergänzt `Payment` um Soft-Delete-Felder (`deleted_at`, `deleted_by`) und eine lesbare Zahlungsnummer (`Z#00001`), analog zu Buchungen.
- Führt `PaymentAuditLog` ein, das Löschung und Wiederherstellung je Zahlung mit Bearbeiter, Zeitpunkt und Vorher-Snapshot protokolliert.
- Ergänzt die Teilnehmeransicht um eine Zahlungstabelle mit Löschaktion sowie ein Zahlungsprotokoll mit Wiederherstellung; beides nur für Administratoren.
- Schließt gelöschte Zahlungen aus allen Saldoberechnungen aus (Einzelabrechnung und Sammelabrechnung), sodass `Gezahlt` und `Offen` korrekt bleiben.
- Ersetzt die nackte `Payment`-Registrierung im Django-Admin durch Soft-Delete- und Wiederherstellungs-Aktionen und registriert `PaymentAuditLog` schreibgeschützt.
- Neue Testabdeckung in `tests/test_payment_audit.py`: Audit-Snapshot beim Löschen, Editor-Sperre, GET-Ablehnung, Ausschluss aus beiden Abrechnungspfaden, Wiederherstellung und Fehlerfälle.
- Merge von `main`: Import-Konflikt in `src/billing/admin.py` und Admin-Handbuch-Konflikt in `src/templates/billing/admin_guide.html` aufgelöst (beide Seiten übernommen); die Migration wurde von `0062` auf `0063_payment_soft_delete_audit` umnummeriert und hängt jetzt an `0062_shift_descriptions`, damit der Migrationsgraph einen einzigen Leaf behält.
- Entfernt eine unvollständige Doppel-Definition der Admin-Aktion `restore_selected_payments` in `src/billing/admin.py`. Python behielt bereits die zweite, vollständige Variante; die erste war toter Code und ließ `ruff` (F811/F841) fehlschlagen.
