# Mobile Django-Admin für Issues #352 und #353

## Zusammenfassung

Responsive, zugängliche mobile Navigation, Tabellen, Filter und Leerzustände im
Django-Admin; deutsche Modell- und Feldbezeichnungen bleiben im Admin konsistent.

Die Filter-ARIA-Anfangsanzeige entspricht dem serverseitig geöffneten Zustand;
Ergebnis- und Paginator-Links sind auf mobilen Viewports touch-gerecht. Die
verbleibenden Camp-Feldbezeichnungen sind auf Deutsch gesetzt. Der E2E-Server
verwendet einen absoluten SQLite-Temp-Pfad, sodass Migration und Cleanup exakt
dieselbe Datenbank treffen und keine Altbestandsdubletten zwischen Läufen bleiben.

Die Modell-Metadaten sind auf dem aktuellen Migrationsstand als Migration 0071
integriert. Die alten, nicht mehr passenden Migrationen aus dem ursprünglichen
#402-Branch wurden nicht übernommen. Die Admin-Mobile-Assets sind nicht Teil des
PWA-`STATIC_ASSETS`-Vertrags; deshalb wurde `PWA_CACHE_VERSION` nicht erhöht.

## Geänderte Dateien

- `src/templates/admin/base_site.html`
- `src/templates/admin/change_list.html`
- `src/static/billing/admin-mobile.css` und `admin-mobile.js`
- `src/billing/models.py` und `src/billing/migrations/0070_*.py`, `0071_*.py`
- fokussierte Admin-Python- und Playwright-Regressionen

Die Review-Nachbesserungen halten den mobilen Menüabstand und 44×44px
Sidebar-Touchflächen ein, schließen versteckte Navigationslinks aus dem
Fokus-Trap aus, zeigen Desktop-Filter standardmäßig an und machen
Changelist-Tabellen als benannte Tastatur-Scrollregion zugänglich. Der
Desktop-Overflow-Schutz bleibt auf Changelists begrenzt, damit breite
Admin-Formulare und Inline-Tabellen nicht abgeschnitten werden.

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
Closes #572
Closes #573
Closes #575
Closes #576
Closes #577
