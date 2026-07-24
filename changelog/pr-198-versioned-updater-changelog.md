# Versionsbasierter Updater-Changelog

- Der Container-Build vergibt eine deterministische Mainline-Version und ordnet jeden Changelog-Eintrag seiner Version zu.
- Der Image-Build lädt die vollständige Git-Historie, damit historische Versionsgrenzen korrekt berechnet werden.
- Der Updater zeigt dadurch alle Änderungen zwischen installierter und verfügbarer Version kumuliert in einer kompakten Übersicht mit aufklappbaren Details an.
- Bestehende revisionsbasierte Image-Metadaten bleiben als Rückwärtskompatibilität unterstützt.
