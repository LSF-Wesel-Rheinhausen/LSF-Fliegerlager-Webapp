# Idempotente Auszahlungen lehnen abweichende Metadaten ab

- `create_credit_payout` prüft bei Idempotenz-Replays jetzt auch externe Referenz und Notiz.
- Referenz und Notiz werden vor Validierung und Speicherung an den Rändern normalisiert; die Modellgrenzen von 120 bzw. 180 Zeichen gelten auch im Service.
- Ein identischer Replay liefert die bestehende Auszahlung zurück und erzeugt keinen zweiten Write; Fehlermeldungen enthalten keine Auszahlungsmetadaten.
- Closes #464
- Ein konkurrierender Unique-Insert wird nur bei sichtbarem passendem Idempotenzschlüssel als Replay behandelt; unbekannte Integritätsfehler bleiben sichtbar. Closes #534
- Historische Rand-Whitespace-Werte werden beim Replay kanonisch verglichen, ohne bestehende Daten umzuschreiben. Closes #535
- PostgreSQL-Concurrency-Test für denselben Schlüssel bei unterschiedlichen Teilnehmern ergänzt. Closes #536
- Replay-Recovery reagiert nur auf den benannten Idempotenz-Constraint beziehungsweise die exakte SQLite-Constraint-Meldung; fremde IntegrityErrors werden erneut ausgelöst. Closes #537
- Die beiden Replay-Recovery-Tests erzeugen den passenden PostgreSQL- oder SQLite-IntegrityError abhängig vom aktiven Backend. Closes #538
