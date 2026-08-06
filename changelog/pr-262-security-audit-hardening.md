# Security-Audit-Härtung

- Setzt das Django-App-Image standardmäßig auf Produktionsmodus, sodass fehlende Produktionskonfiguration den Containerstart sicher abbricht.
- Prüft hochgeladene Rechnungsbelege aus App und Django-Admin anhand konsistenter Endungen, MIME-Typen und Dateisignaturen für PDF, JPEG, PNG und HEIC.
- Liefert geschützte Rechnungsbelege ausschließlich als Download-Anhang aus und deckt manipulierte sowie abgeschnittene Dateien durch Regressionstests ab.
- Erlaubt Metadatenänderungen an Bestandsdatensätzen mit älteren Belegen, ohne die unveränderte Datei nachträglich abzulehnen, und erkennt gültige HEIC-Dateien auch bei längeren, begrenzten `ftyp`-Boxen.
