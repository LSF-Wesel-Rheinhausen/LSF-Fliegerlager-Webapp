### Sicherer Portainer-Updater mit Release-Kanälen

- Behebt den wiederholten Rollback nach einem Neustart des Updaters durch eine idempotente Recovery-Zustandsmaschine.
- Hält den operativen Update-Status klein und speichert Versionskatalog, Changelogs und Migrationsdaten in begrenzten Caches.
- Ergänzt umgebungsgebundene Prod-, Staging- und Dev-Kanäle mit auswählbaren, digestgebundenen Versionen.
- Sortiert den Versionskatalog anhand der GitHub-Package-Zeitstempel; dafür benötigt nur der Updater ein Lesetoken mit `read:packages`.
- Unterstützt explizit erlaubte Nicht-GHCR-Registries über einen begrenzten Katalog ihrer verifizierten Kanalzeiger.
- Warnt vor Downgrades oder abweichenden Migrationen und verlangt dafür eine ausdrückliche Risikobestätigung.
- Behandelt gelöschte Manifeste laufender Images sowie unbekannte Migrationsmanifest-Versionen konservativ als bestätigungspflichtiges Risiko.
- Veröffentlicht geprüfte PR-Builds über einen vertrauenswürdigen Folge-Workflow als Dev, erfolgreiche Main-Builds als Staging und promotet exakt verifizierte Prod-Digests nur manuell.
- Begrenzt GHCR-Katalogabfragen auf ein festes Zeit- und Seitenbudget und beendet sie, sobald je erlaubtem Kanal genügend Versionen vorliegen.
- Ordnet Dev-Promotionen über die vertrauenswürdige Test-Workflow-Run-ID statt über vom PR kontrollierte Image-Zeitstempel.
- Verwendet für Container-Builds den deterministischen Commit-Zeitstempel, damit erneute Builds derselben Revision keine zeitabhängigen Metadaten erzeugen.
