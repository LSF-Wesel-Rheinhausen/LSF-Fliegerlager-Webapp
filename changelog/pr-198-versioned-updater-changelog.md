# Versionsbasierter Updater-Changelog

- Der Container-Build vergibt eine deterministische Mainline-Version und ordnet jeden Changelog-Eintrag seiner Version zu.
- Der Image-Build lädt die vollständige Git-Historie, damit historische Versionsgrenzen korrekt berechnet werden.
- Der Updater zeigt dadurch alle Änderungen zwischen installierter und verfügbarer Version, auch wenn der installierte Commit keinen eigenen Changelog-Eintrag besitzt.
- Bestehende revisionsbasierte Image-Metadaten bleiben als Rückwärtskompatibilität unterstützt.
