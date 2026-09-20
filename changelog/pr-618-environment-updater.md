### Sicherer Portainer-Updater mit Release-Kanälen

- Behebt den wiederholten Rollback nach einem Neustart des Updaters durch eine idempotente Recovery-Zustandsmaschine.
- Hält den operativen Update-Status klein und speichert Versionskatalog, Changelogs und Migrationsdaten in begrenzten Caches.
- Ergänzt umgebungsgebundene Prod-, Staging- und Dev-Kanäle mit auswählbaren, digestgebundenen Versionen.
- Sortiert den Versionskatalog anhand der GitHub-Package-Zeitstempel; dafür benötigt nur der Updater ein Lesetoken mit `read:packages`.
- Warnt vor Downgrades oder abweichenden Migrationen und verlangt dafür eine ausdrückliche Risikobestätigung.
- Veröffentlicht geprüfte PR-Builds über einen vertrauenswürdigen Folge-Workflow als Dev, erfolgreiche Main-Builds als Staging und promotet exakt verifizierte Prod-Digests nur manuell.
