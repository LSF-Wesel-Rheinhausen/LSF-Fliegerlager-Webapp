# Zahlungsaudit nach Soft-Delete unveränderlich halten

- Gelöschte Zahlungen sind im Django-Admin für Teilnehmer, Betrag, Datum, Zahlungsart und Notiz schreibgeschützt.
- Wiederherstellungen validieren den vollständigen Audit-Snapshot und setzen die geprüften Originalwerte transaktional zurück.
- Zeilensperren verhindern parallele Doppel-Wiederherstellungen und doppelte Audit-Einträge.
- Tests decken Crafted-POSTs, aktive Admin-Bearbeitung, Bulk-Tampering, Parallelzugriffe und ungültige Snapshots ab.
