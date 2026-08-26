# Updater startup recovery loop hotfix

- Make the updater wait for a healthy app and retry transient Portainer startup failures within a bounded backoff.
- Let Recovery wait briefly for App runtime convergence instead of redeploying on a transient zero or multiple
  container observation.
- Behandle identische Ziel- und Rollback-Images ohne Mutation: Nur ein healthy verifiziertes Ziel wird automatisch
  abgeschlossen.
