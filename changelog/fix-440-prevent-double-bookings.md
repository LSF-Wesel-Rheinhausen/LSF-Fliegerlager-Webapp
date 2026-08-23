# Kiosk-Schnellbuchungen gegen Doppelbuchungen absichern

- Direkte Kiosk-Schnellbuchungen verwenden einen signierten, einmaligen und camp-/teilnehmergebundenen Token.
- Wiederholte Aktivierung derselben gerenderten Buchung erzeugt höchstens eine Charge; ein neuer Form-Token erlaubt weiterhin eine beabsichtigte identische Buchung.
- Die UI sperrt Schnellbuchungsaktionen unmittelbar und zeigt den Verarbeitungsstatus barrierearm an.
- Closes #525: Die Marker-Semantik wird dokumentiert und Replay mit verändertem Buchungsinhalt bleibt idempotent.
- Closes #526: Ein PostgreSQL-Paralleltest sichert den Produktionsvertrag mit zwei gleichzeitigen Requests ab; SQLite bleibt auf lokale Einzelprozess-Nutzung begrenzt.
- Closes #527: Der Verpflegungsdialog prüft sichtbares Busy-Feedback und genau eine Buchung bei schneller Doppelaktivierung in allen Browsern.

Closes #440
