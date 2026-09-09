# Sichere Wiederherstellung für Admin-Passwörter und Kiosk-PINs

- Ergänzt neutrale Self-Service-Anfragen an den Admin- und Kiosk-Anmeldungen, ohne das Vorhandensein eines Kontos offenzulegen.
- Versendet zeitlich begrenzte Einmal-Links über die bestehende E-Mail-Outbox und über alle aktiven Push-Geräte; das Secret entsteht erst unmittelbar vor jedem Zustellversuch und wird weder in der Outbox noch in der Datenbank im Klartext gespeichert.
- Begrenzt Anfragen dauerhaft pro Client und verwirft frühere, abgelaufene, bereits verwendete, nach einer zwischenzeitlichen Zugangsdatenänderung ungültige sowie zu inaktiven Konten gehörende Links.
- Setzt Admin-Passwörter mit den Django-Validatoren beziehungsweise sichere Teilnehmer- und Begleitpersonen-PINs und hebt bestehende Login-Sperren für Benutzernamen und anfragende IP-Adresse nach erfolgreicher Wiederherstellung auf.
- Kennzeichnet bei gemeinsam genutzten E-Mail-Adressen das betroffene Kiosk-Konto eindeutig und hält systeminterne Wiederherstellungs-E-Mails aus der manuellen Versandübersicht heraus.
- Prüft vor dem Versand erneut, dass die hinterlegte Empfängeradresse noch zum Konto gehört, und verwirft ausstehende E-Mail- sowie Push-Nachrichten automatisch mit einem gelöschten Recovery-Token.
- Bindet persönliche Kiosk-Sitzungen an den aktuellen PIN-Stand, sodass ein erfolgreicher PIN-Reset bereits angemeldete Geräte abmeldet.
- Prüft auch auf teilnehmerbezogenen Kiosk-Routen die vollständige aktive Identität, sodass geänderte Begleitpersonen-PINs keinen bestehenden Zugriff auf Rechnungen oder Auslagen hinterlassen.
- Sperrt bei der Token-Aktivierung und -Einlösung die tatsächliche PIN-Zeile und claimt Recovery-Pushes vor der Token-Rotation atomisch mit einer wiederaufnehmbaren Processing-Lease.
- Stellt Wiederherstellungslinks an alle passenden aktiven Kiosk-Konten einer gemeinsamen Adresse zu und schützt eingegebene Passwörter und PINs in technischen Fehlerberichten.

## Tests

- Pytest-Abdeckung für alle Kontotypen und Kanäle, unbekannte/inaktive Konten, gemeinsam genutzte und nachträglich geänderte Adressen, mehr als zehn passende Kiosk-Konten, Push-only-Konten, Einmaligkeit, zustellungsbezogenen Ablauf, parallele Push-Worker, Wiederholungsversuche, PIN-Zeilensperren, externe Zugangsdatenänderungen, vollständigen Session-Widerruf, sensible POST-Daten, gelöschte Tokens und Rate-Limits.

## Offene Punkte

- Keine.
