# Issue #595: Nutzerfunktionen je Lager steuern

**Status:** Plan; die Implementierung ist noch nicht erfolgt.
**Issue:** Closes #595

## Ziel und Umfang

Admins mit Berechtigung zur Lagerkonfiguration können pro Lager einzelne Nutzerfunktionen abschalten oder freigeben. Die vorhandenen Lager-Einstellungen werden dafür um einen zentralen, nachvollziehbaren Funktionskatalog ergänzt. Er umfasst mindestens Essen/Vorbestellung, Getränke, Anwesenheit, Schichtplanung, Profil- und Familien-/Partnerfunktionen, Spenden, Ausgaben, Selbstregistrierung, optionale Benachrichtigungen sowie Rechnungen, soweit diese bereits als Lager-Einstellung konfiguriert sind.

Jede Funktion wird sowohl in der Oberfläche als auch serverseitig geschützt. Die Prüfung muss für GET und POST in privaten und zentralen Kiosk-Flows gelten. Das Abschalten blendet Nutzeraktionen aus und verhindert direkte URL-, Formular- und API-Aufrufe. Admin-Verwaltung, bestehende Finanztransparenz, Daten, Buchungen und Historie bleiben zugänglich und erhalten.

Bestehende Abschaltflags bleiben wirksam. Neue bekannte Funktionen sind ohne abweichende Einstellung eingeschaltet. Login, Logout, PIN-Zugriff, Kontowiederherstellung, Widerruf bestehender Freigaben und rechtliche Informationen bleiben verfügbar; Rechnungen und Historie behalten ihre bestehenden Sichtbarkeitsregeln. Nicht bekannte Funktionskennungen werden standardmäßig verweigert. Bereits eingeplante optionale Benachrichtigungen prüfen die Freigabe beim Versand erneut; eine während der Sperre veraltete Warteschlange darf später nicht ungeprüft nachgesendet werden. Die Umsetzung berücksichtigt PIN-Recovery, Ablauf und Widerruf bestehender Kiosk-Zugriffe sowie rechtliche und sicherheitsrelevante Zugangswege.

## Umsetzung und Abnahme

- [ ] Bestehende Camp-Einstellungen und Funktionsgrenzen inventarisieren; Katalog und sichere Defaults festlegen.
- [ ] Pro-Lager-Einstellung mit Migration und Rückwärtskompatibilität für bestehende Off-Flags ergänzen.
- [ ] Gemeinsame serverseitige Gate-Prüfung für alle betroffenen GET-/POST-Endpunkte in privatem und zentralem Kiosk einführen; Admin- und Recovery-Wege erhalten.
- [ ] Kiosk-Navigation, Seiten, Formulare und Aktionen passend zur Freigabe darstellen; unbekannte IDs geschlossen behandeln.
- [ ] Benachrichtigungswarteschlange beim tatsächlichen Versand erneut prüfen und veraltete Einträge ohne Replay verwerfen.
- [ ] Django-Tests für Defaults, Migration/alte Flags, unbekannte IDs, direkte GET-/POST-Zugriffe, beide Kiosk-Modi, Admin-Ausnahmen, PIN-Recovery/-Widerruf und Benachrichtigungs-Recheck ergänzen.
- [ ] Lagerübergreifende Isolation, bereits geöffnete Formulare nach Abschaltung, Wiederfreigabe und unveränderte Finanzberechnungen testen. Jede Nutzeraktion muss einem Gate oder einer ausdrücklich erhaltenen Grundfunktion zugeordnet sein.
- [ ] E2E-Tests für die Admin-Konfiguration und gesperrte/freigegebene Nutzeraktionen in beiden Kiosk-Modi ergänzen.
- [ ] Abnahme: abgeschaltete Nutzeraktion ist auch bei direktem Aufruf serverseitig unmöglich; Daten und Historie bleiben erhalten; Admin kann die Funktion wieder freigeben.

## Nicht-Ziele

Kein Plugin-Framework, keine neue Laufzeitabhängigkeit und keine Aufteilung in neue Django-Apps. Keine Löschung oder Bereinigung vorhandener Daten, keine globale Abschaltung von Admin-Funktionen und keine Änderung an fachlichen Berechnungen oder Abrechnungen.

## Abschluss

- [ ] Changelog und relevante Dokumentation ergänzen.
- [ ] Ruff, Django-Checks, Migrationsabgleich, mypy, vollständige Python- und Browserprüfungen ohne lokales Docker abschließen.
- [ ] Unabhängiges Review abschließen; danach PR auf Ready for review setzen. Kein automatischer Merge.

Dieser Draft dokumentiert zunächst nur den Plan. Das Issue wird erst durch den Merge der vollständig implementierten und geprüften Änderung geschlossen.
