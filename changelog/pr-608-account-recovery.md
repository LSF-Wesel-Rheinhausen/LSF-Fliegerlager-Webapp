# Sichere Wiederherstellung für Admin-Passwörter und Kiosk-PINs

- Ergänzt neutrale Self-Service-Anfragen an den Admin- und Kiosk-Anmeldungen, ohne das Vorhandensein eines Kontos offenzulegen.
- Versendet zeitlich begrenzte Einmal-Links über die bestehende E-Mail-Outbox und über alle aktiven Push-Geräte; das Secret entsteht erst unmittelbar vor jedem Zustellversuch und wird weder in der Outbox noch in der Datenbank im Klartext gespeichert.
- Begrenzt Anfragen dauerhaft pro Client und verwirft frühere, abgelaufene, bereits verwendete, nach einer zwischenzeitlichen Zugangsdatenänderung ungültige sowie zu inaktiven Konten gehörende Links.
- Setzt Admin-Passwörter mit den Django-Validatoren beziehungsweise sichere Teilnehmer- und Begleitpersonen-PINs und hebt bestehende Login-Sperren für Benutzernamen, aktuelle E-Mail-Adresse und anfragende IP-Adresse nach erfolgreicher Wiederherstellung auf.
- Kennzeichnet bei gemeinsam genutzten E-Mail-Adressen das betroffene Kiosk-Konto eindeutig und hält systeminterne Wiederherstellungs-E-Mails aus der manuellen Versandübersicht heraus.
- Prüft vor dem Versand erneut, dass die hinterlegte Empfängeradresse noch zum Konto gehört, und verwirft ausstehende E-Mail- sowie Push-Nachrichten automatisch mit einem gelöschten Recovery-Token.
- Bindet persönliche Kiosk-Sitzungen an den aktuellen PIN-Stand, sodass ein erfolgreicher PIN-Reset bereits angemeldete Geräte abmeldet.
- Verwirft auch vor dem Update angelegte Kiosk-Sitzungen ohne PIN-Fingerprint und prüft Benachrichtigungs-Endpunkte über dieselbe vollständige Kiosk-Identität.
- Prüft auch auf teilnehmerbezogenen Kiosk-Routen die vollständige aktive Identität, sodass geänderte Begleitpersonen-PINs keinen bestehenden Zugriff auf Rechnungen oder Auslagen hinterlassen.
- Ermöglicht Push-only-Kiosk-Konten die Wiederherstellung über dieselbe öffentlich sichtbare Teilnehmerauswahl wie beim Kiosk-Login; der E-Mail-Weg bleibt erhalten.
- Redigiert Recovery-Secrets aus Request-Ziel, Pfad und Referrer der Gunicorn-Access-Logs.
- Sperrt bei der Token-Aktivierung und -Einlösung die tatsächliche PIN-Zeile und claimt Recovery-Pushes vor der Token-Rotation atomisch mit einer wiederaufnehmbaren Processing-Lease.
- Stellt Wiederherstellungslinks an alle passenden aktiven Kiosk-Konten einer gemeinsamen Adresse zu und schützt eingegebene Passwörter und PINs in technischen Fehlerberichten.
- Redigiert Recovery-Secrets zusätzlich aus Django-Request-Logs und ordnet Companion-Push-Geräte der authentifizierten Begleitperson statt dem Guardian zu.
- Unterscheidet Picker-Tokens explizit vom E-Mail-Feld, damit E-Mail-Adressen mit `participant-`-Präfix nicht als IDs interpretiert werden.
- Markiert alte teilnehmerbezogene Push-Geräte bei der Umstellung auf getrennte Begleitpersonen-Identitäten als nicht für Recovery verifiziert; redigiert Recovery-Secrets auch aus CSRF-Ablehnungslogs und schließt inaktive Begleitpersonen aus regulären Push-Mitteilungen aus.
- Bindet E-Mail-Recovery-Capabilities mittels domänengetrenntem HMAC an die normalisierte Empfängeradresse, verlangt bereits konfigurierte Zugangsdaten und prüft Kiosk-Push-Berechtigung und Eigentümerschaft unmittelbar vor dem Versand erneut.
- Invalidiert Recovery-Capabilities bei endgültig fehlgeschlagenen oder während der Zustellung entfernten Push-Zielen.
- Redigiert Recovery-Secrets auch in Gunicorn-Fehler- und Django-Entwicklungsserver-Logs und begrenzt die Push-Aufbewahrung auf die Token-Laufzeit.
- Begrenzt Recovery-Anfragen zusätzlich pro normalisierter Identität über einen nicht umkehrbaren HMAC-Schlüssel, ohne bekannte Konten offenzulegen.
- Serialisiert Login-Attempt-Mutationen in einer gemeinsamen sortierten Sperrreihenfolge und leert erfolgreiche Sperren statt sie zu löschen.
- Widerruft nach erfolgreicher Wiederherstellung exakt die Push-Geräte des betroffenen Kontos beziehungsweise verlangt deren erneute Identitätsprüfung.
- Verhindert leere Login-Sperrzeilen bei erfolgreichen Anmeldungen, verwendet pro E-Mail-Zustellung eine frische Claim-Zeit und bereinigt nicht abbildbare Begleitpersonen-Geräte beim Rollback der Eigentümermigration.
- Bindet zugestellte Push-Recovery-Links an das exakte Empfängergerät, sodass Deaktivierung, Entzug der Identitätsprüfung oder Löschen dieses Geräts den Link sofort ungültig macht.
- Widerruft persönliche Recovery-Geräte bei jeder etablierten Passwort- oder PIN-Rotation und verwendet für Zustellung, Bestätigung und Widerruf eine einheitliche Sperrreihenfolge.
- Bereinigt beim Rollback auf das Schema vor der Kontowiederherstellung ausschließlich nicht mehr darstellbare Recovery-E-Mail-Batches samt Zustellungen, bevor die alte Datenbankbedingung wiederhergestellt wird.
- Verifiziert bei der Geräte-Eigentümermigration bestehende Admin-Geräte, widerruft sie bei jedem Django-Admin-Passwortwechsel und hält auch terminale Push-Fehler in der gemeinsamen Recovery-Sperrreihenfolge ab.
- Verarbeitet öffentliche Admin-Recovery-Anfragen über eine persistente Worker-Queue, damit Treffer und Nichttreffer im HTTP-Pfad gleichartig bleiben.
- Verarbeitet auch Kiosk-PIN-Recovery-Anfragen über dieselbe persistente Worker-Queue, sodass E-Mail-Treffer nicht synchron offenlegen, ob eine private Adresse zu einem Kiosk-Konto gehört.
- Entfernt abgearbeitete Recovery-Queue-Einträge einschließlich der eingegebenen Identität atomar und erzeugt bearbeitbare Links ausschließlich aus einem strikt konfigurierten öffentlichen Origin.
- Löscht abgelaufene oder verwendete Recovery-Tokens zusammen mit terminalen E-Mail-/Push-Artefakten, ohne aktive Zustellungen anzutasten, und konfiguriert alle Worker mit dem kanonischen Origin sowie passenden Healthchecks.
- Behält bei mehrdeutigen Transportfehlern und Worker-Neustarts den möglicherweise bereits zugestellten Einmal-Link bis zu seinem ursprünglichen Ablauf gültig und führt zentrale Kiosk-Recoveries über feste, öffentlich einlösbare zentrale Rückwege, ohne in private Sitzungseinstellungen zu wechseln; beide Confirm-Routen werden in Logs redigiert und der lokale Compose-Origin ist vollständig dokumentiert.

## Tests

- Pytest-Abdeckung für alle Kontotypen und Kanäle, unbekannte/inaktive Konten, gemeinsam genutzte und nachträglich geänderte Adressen, mehr als zehn passende Kiosk-Konten, Push-only-Konten, Einmaligkeit, zustellungsbezogenen Ablauf, parallele Push- und E-Mail-Worker, Wiederholungsversuche, PIN-Zeilensperren, externe Zugangsdatenänderungen, vollständigen Session- und Geräte-Widerruf einschließlich Benachrichtigungs-Endpunkten, exakte Push-Gerätebindung, Sperrreihenfolgen, reversible Migrationen, Access-Log-Redaktion, sensible POST-Daten, gelöschte Tokens und Rate-Limits.

## Offene Punkte

- Keine.
