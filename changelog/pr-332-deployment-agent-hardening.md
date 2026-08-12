# Deployment-Agent für F-09, F-10 und F-11 härten

- Begrenze JSON-Request-Bodies, Lese-Timeouts und parallele Update-Agent-Requests; verwende generische Fehlerantworten.
- Serialisiere Update- und Archiv-Backups mit einem gemeinsamen Lock und lege Archive exklusiv mit kryptografischem
  Zufallssuffix an.
- Binde `/install` an den bei `/check` validierten `repo@sha256:...`-Digest, verifiziere den tatsächlich laufenden
  RepoDigest nach dem Healthcheck und rolle bei Abweichungen auf den alten Digest zurück.
- Bewahre bei Multi-Platform-Images den Index-Digest für die Installation, begrenze Header-Wartezeiten bereits am
  akzeptierten Socket und starte bei einem belegten Backup-Lock keinen Rollback ohne Stack-Mutation.
- Ergänze Regressionstests für Grenzwerte, abgebrochene Reads, parallele Requests, Backup-Kollisionen und Digest-
  Wechsel.

Refs #263
