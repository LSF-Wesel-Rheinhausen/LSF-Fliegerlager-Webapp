## Persistente Container-Daten vereinheitlicht

- Datenbank, Medien, Backups, Updater-Status und Web-Push-Schlüssel liegen unter einem konfigurierbaren Host-Ordner.
- Bestehende Named Volumes werden bei der ersten Bereitstellung sicher und idempotent übernommen.
- VAPID-Schlüssel werden bei aktiviertem Web Push automatisch erzeugt und dauerhaft wiederverwendet.
- Hintergrund-Worker erben nicht länger den ausschließlich für die Web-App bestimmten HTTP-Healthcheck.
