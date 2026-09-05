# Sichere Wiederherstellung für Admin-Passwörter und Kiosk-PINs

- Ergänzt neutrale Self-Service-Anfragen an den Admin- und Kiosk-Anmeldungen, ohne das Vorhandensein eines Kontos offenzulegen.
- Versendet zeitlich begrenzte Einmal-Links über die bestehende E-Mail-Outbox und über alle aktiven Push-Geräte; der prüfende Tokenzustand wird nur als Hash gespeichert und Zugangsdaten selbst werden nie übertragen.
- Begrenzt Anfragen dauerhaft pro Client und verwirft frühere, abgelaufene, bereits verwendete sowie zu inaktiven Konten gehörende Links.
- Setzt Admin-Passwörter mit den Django-Validatoren beziehungsweise sichere Teilnehmer-PINs und hebt bestehende Login-Sperren nach erfolgreicher Wiederherstellung auf.

## Tests

- Pytest-Abdeckung für beide Kontotypen und Kanäle, unbekannte/inaktive Konten, Push-only-Konten, Einmaligkeit, Ablauf, erneute Anforderung und Rate-Limits.

## Offene Punkte

- Keine.
