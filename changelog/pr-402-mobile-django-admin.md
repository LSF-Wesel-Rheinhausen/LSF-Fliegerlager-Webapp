# Mobile Django-Admin für Issues #352 und #353

## Zusammenfassung

Responsive, zugängliche mobile Navigation, Tabellen, Filter und Leerzustände im
Django-Admin; deutsche Modell- und Feldbezeichnungen bleiben im Admin konsistent.

Die Modell-Metadaten sind auf dem aktuellen Migrationsstand als Migration 0070
integriert. Die alten, nicht mehr passenden Migrationen aus dem ursprünglichen
#402-Branch wurden nicht übernommen. Die Admin-Mobile-Assets sind nicht Teil des
PWA-`STATIC_ASSETS`-Vertrags; deshalb wurde `PWA_CACHE_VERSION` nicht erhöht.

## Geänderte Dateien

- `src/templates/admin/base_site.html`
- `src/templates/admin/change_list.html`
- `src/static/billing/admin-mobile.css` und `admin-mobile.js`
- `src/billing/models.py` und `src/billing/migrations/0070_*.py`
- fokussierte Admin-Python- und Playwright-Regressionen

## Tests

- RED/GREEN: `tests/test_admin_mobile.py`
- Request-Failure-Allowlist: `tests/requestFailureFilter.test.js`
- Browser-QA: Desktop, Portrait 390×844 und Landscape 844×390
- Playwright: `tests/e2e/admin_mobile.spec.js`

Closes #352
Closes #353
Closes #563
Closes #564
Closes #565
Closes #571
Closes #574
