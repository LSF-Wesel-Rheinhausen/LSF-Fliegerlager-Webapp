# Kiosk Rechnungs-Steuerung, Kiosk-Selbstregistrierung & Visual Alignment Fixes

- Fügt das Feld `show_kiosk_invoices` zum `Camp`-Modell und Admin-Formular hinzu, um Kiosk-Rechnungsanzeigen und PDF-Downloads pro Lager ein- oder auszuschalten.
- Implementiert die **Kiosk-Selbstregistrierung**: Teilnehmer können sich über einen Button auf der Kiosk-Login-Seite direkt für das Lager eintragen (Status `PENDING_APPROVAL`).
- Implementiert das **Admin-Freigabe-Dashboard**: Lagerleiter sehen offene Registrierungen in `camp_detail.html` mit Buttons zum Freigeben (`REGISTERED`) oder Ablehnen.
- Behebt das **Datums-Eingabefeld-Problem bei Lagerbearbeitung**: Alle `DateInput`-Widgets verwenden nun explizit das ISO-Format `format="%Y-%m-%d"`, sodass HTML5 `<input type="date">` bei der Bearbeitung vorhandener Lager oder Daten nie leer dargestellt wird.
- Erweitert die Kiosk-Login-Seite um den Pre-Camp Countdown-Banner ("Noch X Tage bis Lagerbeginn!").
- Komprimiert die Rechnungs-Karte im Kiosk auf max. 2 Direkt-Aktionen (Live-Abrechnung + neueste finale Abrechnung) und verbirgt ältere Läufe in einem einklappbaren Archiv (`<details>`).
- Behebt Grid-Abstands- und Höhenausrichtungen in `.kiosk-grid`.
- Erhöht `PWA_CACHE_VERSION` auf 10 für aktualisierte Statische Assets.
