# Manuelle Push-Benachrichtigungen und Kiosk-Ankündigungen

- Erweitert den Informationsversand (`camps/<id>/emails/information/`) um freie Kanalwahl (*Nur E-Mail*, *Nur Push*, *E-Mail & Push*).
- Führt `CampAnnouncement` für Kiosk-Ankündigungen ein, die im Kiosk-Hero-Bereich eingeblendet werden.
- Reiht Push-Benachrichtigungen für registrierte Geräte der ausgewählten Teilnehmer bei manuellem Versand in die Outbox ein.
