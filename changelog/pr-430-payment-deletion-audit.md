# Auditierbares Löschen von eingetragenen Zahlungen

- Ergänzt `Payment` um Soft-Delete-Felder (`deleted_at`, `deleted_by`) und eine lesbare Zahlungsnummer (`Z#00001`), analog zu Buchungen.
- Führt `PaymentAuditLog` ein, das Löschung und Wiederherstellung je Zahlung mit Bearbeiter, Zeitpunkt und Vorher-Snapshot protokolliert.
- Ergänzt die Teilnehmeransicht um eine Zahlungstabelle mit Löschaktion sowie ein Zahlungsprotokoll mit Wiederherstellung; beides nur für Administratoren.
- Schließt gelöschte Zahlungen aus allen Saldoberechnungen aus (Einzelabrechnung und Sammelabrechnung), sodass `Gezahlt` und `Offen` korrekt bleiben.
- Ersetzt die nackte `Payment`-Registrierung im Django-Admin durch Soft-Delete- und Wiederherstellungs-Aktionen und registriert `PaymentAuditLog` schreibgeschützt.
- Neue Testabdeckung in `tests/test_payment_audit.py`: Audit-Snapshot beim Löschen, Editor-Sperre, GET-Ablehnung, Ausschluss aus beiden Abrechnungspfaden, Wiederherstellung und Fehlerfälle.
- Merge von `main`: Import-Konflikt in `src/billing/admin.py` und Admin-Handbuch-Konflikt in `src/templates/billing/admin_guide.html` aufgelöst (beide Seiten übernommen); die Migration wurde von `0062` auf `0063_payment_soft_delete_audit` umnummeriert und hängt jetzt an `0062_shift_descriptions`, damit der Migrationsgraph einen einzigen Leaf behält.
- Entfernt eine unvollständige Doppel-Definition der Admin-Aktion `restore_selected_payments` in `src/billing/admin.py`. Python behielt bereits die zweite, vollständige Variante; die erste war toter Code und ließ `ruff` (F811/F841) fehlschlagen.
- Zweiter Merge von `main` (nach #433): In `calculate_participant_settlement` wurden beide Seiten übernommen — der `family_members`-Prefetch mit `to_attr="settlement_family_members"` aus `main` und der Soft-Delete-Filter `Prefetch("payments", queryset=Payment.objects.filter(deleted_at__isnull=True))` aus diesem Branch. Die Migration heißt jetzt `0065_payment_soft_delete_audit` und hängt an `0064_make_attendance_tracking_internal`. `tests/test_kiosk.py` wurde vollständig von `main` übernommen, da #433 die Uhrzeit-Abhängigkeit der Kiosk-Registrierungstests mit der Fixture `kiosk_registration_today` behebt.
