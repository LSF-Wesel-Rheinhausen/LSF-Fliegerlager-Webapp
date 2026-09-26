# Recovery-Formulare hinter CSRF-Schutz repariert

- Recovery-Seiten verwenden jetzt `Referrer-Policy: strict-origin` statt `no-referrer`.
- Dadurch bleibt der Recovery-Pfad inklusive Token aus dem `Referer`, während Browser bei Formular-POSTs weiterhin eine gültige Origin für Djangos CSRF-Prüfung senden können.
- `Cache-Control: no-store` bleibt unverändert.

Fixes #616.
