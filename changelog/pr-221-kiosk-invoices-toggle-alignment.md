# Kiosk Rechnungs-Steuerung, Login Pre-Camp Features & Visual Alignment Fixes

- Fügt das Feld `show_kiosk_invoices` zum `Camp`-Modell und Admin-Formular hinzu, um Kiosk-Rechnungsanzeigen und PDF-Downloads pro Lager ein- oder auszuschalten.
- Erweitert die Kiosk-Login-Seite um den Pre-Camp Countdown-Banner ("Noch X Tage bis Lagerbeginn!") und Registrierungshinweise.
- Komprimiert die Rechnungs-Karte im Kiosk auf max. 2 Direkt-Aktionen (Live-Abrechnung + neueste finale Abrechnung) und verbirgt ältere Läufe in einem einklappbaren Archiv (`<details>`).
- Behebt Grid-Abstands- und Höhenausrichtungen in `.kiosk-grid` durch `align-items: stretch`.
- Erhöht `PWA_CACHE_VERSION` auf 10 für aktualisierte Statische Assets.
