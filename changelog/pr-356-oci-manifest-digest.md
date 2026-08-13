# OCI-Manifest-Digest beim Deployment-Update validieren

Der Deployment-Agent berechnet fehlende OCI-Manifest-Digests aus den exakt empfangenen Bytes, validiert vorhandene Digest-Header unabhängig von ihrer Groß-/Kleinschreibung und bildet ungültige Registry-Metadaten sicher auf eine verständliche Operator-Meldung ab.
