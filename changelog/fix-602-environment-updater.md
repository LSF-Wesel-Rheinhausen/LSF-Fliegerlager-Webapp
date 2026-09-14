### Sicherer Portainer-Updater mit Release-Kanälen

- Behebt den wiederholten Rollback nach einem Neustart des Updaters durch eine idempotente Recovery-Zustandsmaschine.
- Hält den operativen Update-Status klein und speichert Versionskatalog, Changelogs und Migrationsdaten in begrenzten Caches.
- Ergänzt umgebungsgebundene Prod-, Staging- und Dev-Kanäle mit auswählbaren, digestgebundenen Versionen.
- Warnt vor Downgrades oder abweichenden Migrationen und verlangt dafür eine ausdrückliche Risikobestätigung.
- Veröffentlicht geprüfte PR-Builds als Dev, erfolgreiche Main-Builds als Staging und promotet Prod-Digests nur manuell.
