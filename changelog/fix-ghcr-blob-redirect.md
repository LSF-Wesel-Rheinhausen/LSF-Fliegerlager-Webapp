# GHCR Config-Blob Redirects

## Zusammenfassung

Erlaubt sichere, begrenzte HTTPS-Redirects ausschließlich für digest-adressierte OCI-Config-Blobs. Manifest- und Bearer-Token-Requests bleiben redirect-frei; Cross-Authority-Credentials werden entfernt und Config-Bytes vor dem JSON-Parsing digest-validiert.

## Geänderte Dateien

- `deployment_agent.py`
- `tests/test_deployment_agent.py`

## Tests

- Fokussierte Deployment-Agent-Tests
- Vollständige lokale Verifikation vor PR-Erstellung

## Offene Punkte

- Der öffentliche GHCR-Probe-Request war ohne Package-Berechtigung HTTP 401; es wurden keine URLs oder Signatur-Querys protokolliert.
