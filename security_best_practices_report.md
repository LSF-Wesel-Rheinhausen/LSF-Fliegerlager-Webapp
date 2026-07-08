# Security Best Practices Report

## Executive Summary

Der Audit vom 7. Juli 2026 ergab ein durchweg positives Bild der Sicherheitsarchitektur. Es wurden automatisierte Scans (`npm audit`, `pip-audit`, `bandit`) sowie ein manueller Review des Codes durchgeführt.
Alle im vorherigen Audit (8. Juni 2026) behobenen Lücken (SEC-001 bis SEC-003) sind weiterhin stabil geschlossen. Es wurden keine neuen Injection-Vulnerabilities (SQLi, XSS, SSRF) oder unsicheren Konfigurationen entdeckt. Das verbleibende Risiko im Kiosk-Modus (SEC-004) ist bekannt und wird als betriebliches Restrisiko akzeptiert, sofern keine öffentlichen Kiosk-Terminals ohne Einmal-Code eingesetzt werden.

## Behobene Findings (Historisch)

### SEC-001: Unsichere Produktions-Fallbacks
- **Fix:** Bei `DJANGO_DEBUG=0` sind nun ein mindestens 50 Zeichen langer Schlüssel und explizite Hosts Pflicht.

### SEC-002: Beweglicher und zeitweise kompromittierter Trivy-Action-Pin
- **Fix:** Pin auf den verifizierten Commit von Trivy Action v0.36.0.

### SEC-003: Unbegrenzte Import- und PIN-Versuche
- **Fix:** 5-MB-Dateilimit, Rate Limiting nach Fehlversuchen.

## Aktuelle Findings (7. Juli 2026)

### SEC-004: Selbstvergabe einer noch nicht gesetzten Kiosk-PIN (Verbleibendes Risiko)

- **Severity:** Medium
- **Location:** `src/billing/views.py::kiosk_login`, `src/billing/views.py::kiosk_pin_setup`
- **Evidence:** Teilnehmer ohne gesetzte PIN werden direkt in den PIN-Einrichtungsfluss geleitet.
- **Impact:** Auf einem öffentlich erreichbaren Kiosk könnte eine andere Person einen noch nicht aktivierten Teilnehmer auswählen und dessen PIN zuerst setzen.
- **Mitigation:** Kiosk nur auf kontrollierten Geräten beziehungsweise Netzen bereitstellen oder PINs vor Freigabe administrativ setzen. Für öffentliche Erreichbarkeit ist künftig ein separater Einmalcode- oder Einladungsfluss erforderlich.
- **Status:** *Akzeptiertes Restrisiko.*

### SEC-005: Bandit SAST Alerts (False Positives)

- **Severity:** Low/Info
- **Location:** `src/billing/migrations/0013_remove_legacy_charge_cancellation_columns.py`, `src/billing/deployment_updates.py`, `src/config/settings.py`
- **Evidence:** Der automatisierte SAST-Scanner `bandit` meldete:
  1. `urllib.request.urlopen` (potenzielle SSRF)
  2. SQL-String-Konstruktion in der Datenbank-Migration
  3. Hartcodiertes Passwort "dev-only-change-me" in `settings.py`
- **Mitigation:** Nach manueller Analyse wurden alle drei Funde als False Positives bzw. bereits gesichert eingestuft:
  1. SSRF ist nicht möglich, da `UPDATE_AGENT_URL` aus den Settings stammt und der Pfad fest kodiert ist.
  2. Die Migration nutzt sicheres Quoting über den Schema-Editor (`quote_name`), was SQLi verhindert.
  3. `settings.py` blockiert den Start im Produktionsmodus (`DEBUG=0`), falls das Standardpasswort noch gesetzt ist.

## Prüfungen

- Django Deployment Check mit HTTPS-Produktionskonfiguration: geprüft
- `npm audit --audit-level=high`: 0 Schwachstellen gefunden
- `pip-audit -r requirements-dev.txt`: Keine Schwachstellen gefunden
- `bandit -r src/`: 3 False Positives, 0 echte Vulnerabilities
- Manueller Code Review:
  - Zugriffskontrolle (IDOR-Prävention) funktioniert korrekt über Rollen-Decorators.
  - XLSX/CSV-Dateiuploads sind via `data_only=True` (openpyxl) und Größenlimits abgesichert.
