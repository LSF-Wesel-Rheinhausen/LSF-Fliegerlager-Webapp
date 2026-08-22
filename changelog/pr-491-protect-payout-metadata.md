# Issue #466: Auszahlung-Metadaten schützen

- Gemeinsame Validierung für `CreditPayout.external_reference` und `note` an Model-, Form- und Service-Grenze ergänzt.
- Repräsentative IBAN-, Karten-, PayPal- und Telefonkoordinaten werden abgelehnt; harmlose Referenzen und leere Werte bleiben zulässig.
- Bearbeiter sehen in der Teilnehmeransicht weiterhin Auszahlung, Betrag und Art, aber keine Metadaten. Admins und Superuser behalten die Audit-Sicht, auch bei historischem Altbestand.
- RED: Die neuen Zahlungskoordinaten- und Berechtigungstests schlugen vor der Implementierung erwartungsgemäß fehl.
- GREEN: Nach der Implementierung laufen die fokussierten Credit-Payout-Tests grün.
- #487: Eigenständige gültige E-Mail-Adressen werden an Model-, Form- und Service-Grenze abgelehnt; harmlose Nicht-E-Mail-Referenzen bleiben zulässig.
- #488: IBAN-Kandidaten werden vor Prüfung kanonisch von Unicode-Whitespace (einschließlich U+00A0 und U+202F) normalisiert; harmloser Unicode-Text bleibt unverändert zulässig.
- #489: Die Kartenerkennung ist auf eigenständige Kartenwerte begrenzt. Visa- und Mastercard-Testnummern bleiben blockiert, kontextfreie Business-IDs wie `Ticket 1234567890128` werden akzeptiert.
- #490: Luhn-valide Visa-/Mastercard-Kartennummern werden auch eingebettet in Freitext erkannt und blockiert, ohne beliebige Textpräfixe als Whitelist zu verwenden.
