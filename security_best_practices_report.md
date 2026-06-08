# Security Best Practices Report

## Executive Summary

Der Audit vom 8. Juni 2026 fand keine bekannten npm-Schwachstellen und keine direkten SQL-, Command-, Template- oder Deserialisierungs-Injection-Sinks. Drei konkrete Hardening-Lücken wurden behoben. Ein betrieblicher Restrisiko-Hinweis bleibt für die Kiosk-Selbstvergabe von PINs bestehen.

## Behobene Findings

### SEC-001: Unsichere Produktions-Fallbacks

- **Severity:** High
- **Location:** `src/config/settings.py`
- **Evidence:** Produktion konnte zuvor mit bekanntem Dev-Schlüssel, Wildcard-Hosts und ohne sichere HTTPS-Cookies starten.
- **Impact:** Fehlkonfigurierte Deployments konnten Signaturen und Sessions gefährden oder Host-Header-Angriffe ermöglichen.
- **Fix:** Bei `DJANGO_DEBUG=0` sind nun ein mindestens 50 Zeichen langer Schlüssel und explizite Hosts Pflicht. `DJANGO_HTTPS=1` aktiviert Redirect und sichere Cookies; Proxy- und HSTS-Vertrauen bleiben explizit opt-in.

### SEC-002: Beweglicher und zeitweise kompromittierter Trivy-Action-Pin

- **Severity:** High
- **Location:** `.github/workflows/security.yml`
- **Evidence:** `aquasecurity/trivy-action@master` verwendete einen veränderlichen Branch. Trivy Actions unter 0.35.0 waren im März 2026 von einem Supply-Chain-Angriff betroffen.
- **Impact:** Ein kompromittierter Action-Ref kann CI-Secrets oder Repository-Inhalte exfiltrieren.
- **Fix:** Pin auf den verifizierten Commit von Trivy Action v0.36.0; Pre-commit-, Ruff- und Gitleaks-Hooks wurden ebenfalls aktualisiert.

### SEC-003: Unbegrenzte Import- und PIN-Versuche

- **Severity:** Medium
- **Location:** `src/billing/forms.py`, `src/billing/importers.py`, `src/billing/models.py`
- **Evidence:** Importdateien hatten kein Größen-/Zeilenlimit; bestehende Kiosk-PINs konnten unbegrenzt ausprobiert werden.
- **Impact:** Speicher-/CPU-Belastung durch große Dateien sowie vereinfachtes Erraten kurzer PINs.
- **Fix:** 5-MB-Dateilimit, erlaubte Endungen, UTF-8-/XLSX-Fehlerbehandlung, 5.000-Zeilenlimit und fünfminütige PIN-Sperre nach fünf Fehlversuchen.

## Verbleibendes Risiko

### SEC-004: Selbstvergabe einer noch nicht gesetzten Kiosk-PIN

- **Severity:** Medium
- **Location:** `src/billing/views.py::kiosk_login`, `src/billing/views.py::kiosk_pin_setup`
- **Evidence:** Teilnehmer ohne gesetzte PIN werden direkt in den PIN-Einrichtungsfluss geleitet.
- **Impact:** Auf einem öffentlich erreichbaren Kiosk könnte eine andere Person einen noch nicht aktivierten Teilnehmer auswählen und dessen PIN zuerst setzen.
- **Mitigation:** Kiosk nur auf kontrollierten Geräten beziehungsweise Netzen bereitstellen oder PINs vor Freigabe administrativ setzen. Für öffentliche Erreichbarkeit ist künftig ein separater Einmalcode- oder Einladungsfluss erforderlich.

## Prüfungen

- Django Deployment Check mit HTTPS-Produktionskonfiguration
- `npm audit --audit-level=high`: keine bekannten Schwachstellen
- `pip-audit -r requirements-dev.txt`: keine bekannten Schwachstellen
- Ruff, Ruff-Format, Mypy, Django Check und Migrationsprüfung: bestanden
- Pytest: 194 Tests bestanden
- Playwright: 45 Tests in Chromium, Firefox und WebKit bestanden
- Pre-commit inklusive Gitleaks: bestanden
- Trivy CI-Scan auf unveränderlichen, gepatchten Action-Commit aktualisiert

Ein lokaler Trivy-Container-Scan war in der WSL-Umgebung ohne Docker nicht ausführbar. Der Scan bleibt als verpflichtender CI-Job aktiv.
