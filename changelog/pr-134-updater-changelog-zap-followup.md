## Updater-Changelog und ZAP-Follow-up

- Der Deployment-Updater zeigt Changelog-Einträge zwischen installierter und verfügbarer Revision an.
- Container-Builds veröffentlichen ein strukturiertes Changelog-Manifest als OCI-Metadatum.
- Die ZAP-Baseline scannt den production-nahen Gunicorn/WhiteNoise-Container und nutzt eine dokumentierte Rules-Datei für akzeptierte Info-Findings.
- Inline-Script- und Style-Blöcke werden per CSP-Nonce erlaubt, ohne `unsafe-inline` in `script-src` oder `style-src`.
