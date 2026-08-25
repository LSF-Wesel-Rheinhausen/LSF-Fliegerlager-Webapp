# Admin-Tabellen sortier- und filterbar (Issue #519)

## Zusammenfassung

Alle Admin-Tabellen lassen sich jetzt clientseitig sortieren und viele zusätzlich filtern.
Ein neues Vanilla-JS-Modul (`table_tools.js`) erweitert Tabellen per Datenattribut
(`data-sortable`, `data-filterable`): Spaltenköpfe werden zu echten Sortier-Buttons mit
`aria-sort`, ein Suchfeld über der Tabelle blendet nicht passende Zeilen aus und zeigt
„X von Y Zeilen“ per Live-Region an. Zahlen (`1.234,56 €`), deutsche Datumsangaben
(`TT.MM.JJJJ`) und Texte werden locale-korrekt verglichen; leere Zellen sortieren immer
ans Ende. Auf Mobilgeräten erhalten Karten-Tabellen (`responsive-record-table`) ein
Sortier-Auswahlfeld, da die Kopfzeile dort ausgeblendet ist. Ohne JavaScript bleiben alle
Tabellen unverändert nutzbar (Progressive Enhancement).

Ausgenommen sind die Formset-Tabelle der Preisregeln (positionsabhängige Formularindizes),
die statische Übernachtungsgruppen-Tabelle der Positionsauswertung sowie alle Kiosk-Seiten.

## Geänderte Dateien

- `src/static/billing/table_tools.js` (neu)
- `src/static/billing/app-v8.css`
- `src/templates/base.html`
- `src/billing/pwa_views.py` (PWA-Cache-Version 39 → 40, neues Asset)
- 19 Admin-Templates unter `src/templates/billing/` (Datenattribute an Tabellen und Spalten)
- `tests/test_pwa.py`
- `tests/e2e/admin_table_tools.spec.js` (neu)

## Tests

- Playwright: Sortieren auf- und absteigend mit `aria-sort`-Wechsel, Filtern mit
  Zeilenzähler, Platzhalterzeilen bleiben bei Sortierung/Filterung erhalten,
  mobiles Sortier-Auswahlfeld auf Karten-Tabellen, keine hängenden ARIA-Referenzen,
  Sortier-Bedienelemente sind echte Buttons (Chromium, Firefox, WebKit)
- pytest: PWA-Cache-Namen und Asset-Liste inklusive `table_tools.js`

## Offene Punkte

- Keine.
