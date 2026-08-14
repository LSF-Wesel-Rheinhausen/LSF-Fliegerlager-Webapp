# Mobile Django-Admin für Issues #352 und #353

## Zusammenfassung

Responsive, zugängliche mobile Navigation, Tabellen, Filter und Leerzustände im
Django-Admin; deutsche Modell- und Feldbezeichnungen bleiben im Admin konsistent.

## Geänderte Dateien

- `src/templates/admin/base_site.html`
- `src/templates/admin/change_list.html`
- `src/static/billing/admin-mobile.css` und `admin-mobile.js`
- `src/billing/models.py` sowie die Metadatenmigration
- fokussierte Admin-Python- und Playwright-Regressionen

## Tests

- RED/GREEN: `tests/test_admin_mobile.py`
- Browser-QA: Portrait 390×844 und Landscape 844×390 mit agent-browser
- Playwright: `tests/e2e/admin_mobile.spec.js`
- Vollständige lokale Checks folgen vor Commit.

## Offene Punkte

- Kein neues Paket und keine Änderung an PR #390.
