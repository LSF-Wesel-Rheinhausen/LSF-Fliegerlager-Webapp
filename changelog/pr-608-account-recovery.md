# Sichere Wiederherstellung für Admin-Passwörter und Kiosk-PINs

- Ergänzt neutrale Self-Service-Anfragen an den Admin- und Kiosk-Anmeldungen, ohne das Vorhandensein eines Kontos offenzulegen.
- Versendet zeitlich begrenzte Einmal-Links über die bestehende E-Mail-Outbox und über alle aktiven Push-Geräte; das Secret entsteht erst unmittelbar vor jedem Zustellversuch und wird weder in der Outbox noch in der Datenbank im Klartext gespeichert.
- Begrenzt Anfragen dauerhaft pro Client und verwirft frühere, abgelaufene, bereits verwendete, nach einer zwischenzeitlichen Zugangsdatenänderung ungültige sowie zu inaktiven Konten gehörende Links.
- Setzt Admin-Passwörter mit den Django-Validatoren beziehungsweise sichere Teilnehmer- und Begleitpersonen-PINs und hebt bestehende Login-Sperren für Benutzernamen und anfragende IP-Adresse nach erfolgreicher Wiederherstellung auf.
- Kennzeichnet bei gemeinsam genutzten E-Mail-Adressen das betroffene Kiosk-Konto eindeutig und hält systeminterne Wiederherstellungs-E-Mails aus der manuellen Versandübersicht heraus.
- Prüft vor dem Versand erneut, dass die hinterlegte Empfängeradresse noch zum Konto gehört, und verwirft ausstehende E-Mail- sowie Push-Nachrichten automatisch mit einem gelöschten Recovery-Token.
- Bindet persönliche Kiosk-Sitzungen an den aktuellen PIN-Stand, sodass ein erfolgreicher PIN-Reset bereits angemeldete Geräte abmeldet.

## Tests

- Pytest-Abdeckung für alle Kontotypen und Kanäle, unbekannte/inaktive Konten, gemeinsam genutzte und nachträglich geänderte Adressen, Push-only-Konten, Einmaligkeit, zustellungsbezogenen Ablauf, Wiederholungsversuche, externe Zugangsdatenänderungen, Session-Widerruf, gelöschte Tokens und Rate-Limits.

## Offene Punkte

- Keine.
