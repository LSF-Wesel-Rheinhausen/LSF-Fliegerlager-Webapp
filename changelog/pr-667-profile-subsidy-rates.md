# PR #667: Förderwerte im Jugendgruppenprofil

- Ergänzt eine schreibgeschützte Übersicht der eigenen Jugendgruppenfaktoren und der effektiven Förderung je anwendbarer Preisregel im Kioskprofil.
- Nutzt die vorhandene Förderberechnung und hält Familienprofile strikt von den Fördersätzen des Zahlungskontos getrennt.
- Geänderte Dateien: `src/billing/services.py`, `src/billing/profile_views.py`, `src/templates/billing/kiosk_profile.html`, `tests/test_kiosk_profile_subsidy.py`, `tests/e2e/kiosk_profile_subsidy.spec.js`, `docs/plans/issue-363-profile-subsidy-rates.md`.
- Verifiziert: 8 gezielte Django-Tests; vollständige Python-Prüfung mit 2307 bestanden und 19 übersprungen; Ruff, Formatierung, Django-Check, Migrationsabgleich und mypy erfolgreich. Unabhängiges Review abgeschlossen.
- Die Browser-Gesamtprüfung hatte 380 bestandene und 1 übersprungenen Test; Fehler im neuen E2E-Test betrafen den generierten Standardpreis-Namen und das responsive Kiosk-Menü. Der Standardpreisname ist korrigiert; der Menütest verwendet jetzt den Desktop-Button oder den mobilen Navigationslink und öffnet den Profil-Link im Menüdialog.
- Fokussierte Browser-Abnahme nach den Testkorrekturen: 3 bestanden in Chromium, Firefox und WebKit (Desktop und 390 px).
