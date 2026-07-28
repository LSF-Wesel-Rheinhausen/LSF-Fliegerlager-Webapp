# PWA und Push-Benachrichtigungen

## Gerätemodi

- `/kiosk/` ist für private Geräte. Die persönliche PIN-Anmeldung endet beim Schließen von Browser oder PWA; Push kann
  nach einer ausdrücklichen Browserfreigabe aktiviert werden.
- `/central/kiosk/` ist für gemeinsam verwendete Tablets. Dieser Modus meldet nach 120 Sekunden Inaktivität ab und
  stellt keine Push-Endpunkte bereit.
- Verwaltungsseiten, privater Kiosk und zentraler Kiosk besitzen getrennte Manifeste, Service-Worker-Scopes und Caches.

Vor beiden Kiosk-Modi steht der gemeinsame Lager-PIN. Nach erfolgreicher Eingabe erhält das Gerät ein 30 Tage gültiges,
signiertes `HttpOnly`-Cookie mit `SameSite=Lax`; es enthält weder PIN noch Teilnehmerdaten. Jede geschützte Anfrage
prüft zusätzlich das aktive Lager und dessen aktuelle Widerrufsgeneration in der Datenbank. Ein Admin kann in der
Lagerübersicht den PIN ändern oder alle ausgestellten Lagerzugänge gleichzeitig widerrufen. Danach erscheint auf
jedem Gerät erneut die Lager-PIN-Abfrage, während der persönliche Teilnehmer-PIN unverändert bleibt.

Zentrale Geräte müssen den vollständigen Pfad als Lesezeichen oder PWA-Startseite verwenden. Der Pfad ist kein Secret;
Lager-PIN, persönlicher PIN und die kurze zentrale Teilnehmer-Session bilden gemeinsam die Sicherheitsgrenze.

## Offline-Grenzen

Der Service Worker speichert ausschließlich statische CSS-/JavaScript-Dateien, Icons, Logo und die generische
Offline-Seite. Serverseitig gerenderte Geschäftsdaten, Formulare, Uploads, Exporte und Nicht-GET-Anfragen werden nicht
gecached oder offline eingereiht. Eine Navigation ohne Netzwerk zeigt deshalb nur den Offline-Hinweis.

Manifest, Service Worker und statische Assets bleiben als technische PWA-Ressourcen erreichbar. Ohne gültigen
Lagerzugang liefern Geschäftsrouten keine Daten und nehmen keine schreibenden Requests an.

## Push-Betrieb

Push verwendet `pywebpush`, VAPID und eine Datenbank-Outbox. Der Browser fragt die Berechtigung erst nach Betätigung
von „Benachrichtigungen aktivieren“ an. Endpoints und Browser-Schlüssel werden gespeichert, aber weder angezeigt noch
geloggt. Benachrichtigungen enthalten keine PINs, Belege oder Secrets.

Konfiguration:

```dotenv
WEB_PUSH_ENABLED=1
WEB_PUSH_VAPID_PUBLIC_KEY=
WEB_PUSH_VAPID_PRIVATE_KEY=
WEB_PUSH_VAPID_SUBJECT=mailto:admin@example.org
WEB_PUSH_WORKER_INTERVAL_SECONDS=60
```

Bei leerem Schlüsselpaar erzeugt der App-Container einmalig VAPID-Schlüssel in
`PERSISTENCE_DIR/secrets/webpush/`. Der Push-Worker liest dieselben Dateien schreibgeschützt. Vorhandene explizite
Umgebungswerte haben Vorrang; ist nur ein Wert gesetzt oder nur eine Schlüsseldatei vorhanden, bricht der Start ab,
statt unbemerkt neue Subscriptions ungültig zu machen.

Außerhalb von `localhost` setzen PWA und Push einen vertrauenswürdigen HTTPS-Origin voraus. Der Compose-Service
`push-worker` führt `python manage.py run_push_worker --loop` aus. Temporäre Versandfehler werden höchstens fünfmal
wiederholt; nicht mehr vorhandene Browser-Subscriptions werden bei HTTP 404/410 gelöscht. Abgeschlossene
Outbox-Metadaten werden nach 30 Tagen entfernt.
