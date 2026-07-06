# Portainer SSL-Verifikation konfigurierbar (PR TBD)

Der Portainer-basierte Update-Agent kann die TLS-Zertifikatsprüfung für interne Portainer-Instanzen mit Self-Signed-Zertifikat gezielt deaktivieren.

### Update-Agent
- Neue Option `PORTAINER_VERIFY_SSL` mit sicherem Default `true`.
- `PORTAINER_VERIFY_SSL=false` deaktiviert die Zertifikatsprüfung ausschließlich für Portainer-API-Requests.
- Registry-/GHCR-Zugriffe bleiben von der Option getrennt und verifizieren TLS weiterhin normal.
- Ungültige Werte wie `0` werden mit einer klaren Konfigurationsmeldung abgelehnt.

### Dokumentation
- `.env.example`, `deploy/.env.example`, `README.md` und `deploy/README.md` dokumentieren die neue Option.
- Eine kurze Dependency-Graph-Audit-Notiz dokumentiert den aktuellen Projektstand.
