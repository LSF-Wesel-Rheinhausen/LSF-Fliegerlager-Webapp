# Issue #363: Hilfs- und Berufssatz im Jugendgruppenprofil anzeigen

**Status:** Implementiert; unabhängiges Review abgeschlossen. Browser-Abnahme in Chromium, Firefox und WebKit erfolgreich.
**Issue:** Closes #363

## Ziel und Umfang

Teilnehmende einer Jugendgruppe sehen im eigenen Kiosk-Profil ihre gespeicherten Hilfs- und Berufssätze sowie die daraus berechnete effektive Förderung. Die effektive Förderung wird je anwendbarer Preisregel mit dem bestehenden Berechnungsservice ermittelt, einschließlich dessen Deckelung. Ein Satz von 0 ist ein gültiger, sichtbarer Wert und darf nicht wie ein fehlender Wert behandelt werden.

Die Anzeige ist rein lesend. Sie verwendet die bestehenden Berechtigungen und Berechnungen, verändert keine Preise oder Buchungen und zeigt keine Werte oder Identität anderer Familienmitglieder an. Die Profil- und Finanzanzeige bleibt auch dann verfügbar, wenn Buchungsmodule aus Issue #595 deaktiviert sind.

## Umsetzung und Abnahme

- [x] Bestehenden Berechnungsservice und eigene Profilansicht verwenden; keine parallele Berechnungslogik einführen.
- [x] Hilfssatz, Berufssatz und effektive Förderung für jede anwendbare Preisregel verständlich und lokalisiert darstellen.
- [x] Nullwerte ausdrücklich anzeigen; bei nicht anwendbarer Preisregel oder Nicht-Jugendgruppe die vorhandene Fachlogik respektieren.
- [x] Familien-/Partneransichten auf Identitätstrennung prüfen; keine Fördersätze anderer Personen in das eigene Profil übernehmen.
- [x] Django-Tests für Berechnungsservice, Satz 0, Deckelung, mehrere Preisregeln und Berechtigungs-/Identitätsgrenzen ergänzen.
- [x] E2E-Test für die eigene Profilanzeige sowie für die Abwesenheit fremder Familienwerte ergänzen.
- [x] Abnahme: Anzeige entspricht dem Service je Preisregel und bleibt lesend; Buchungsmodul-Schalter ändern ihre Verfügbarkeit nicht.

## Nicht-Ziele

Keine Eingabe oder Änderung von Fördersätzen durch Teilnehmende und keine Änderung an Preisregeln, Buchungen oder Abrechnungen.

## Abschluss

- [x] Changelog und relevante Dokumentation ergänzen.
- [x] Fokussierte Browser-Abnahme ohne lokales Docker abschließen.
- [x] Ruff, Django-Checks, Migrationsabgleich, mypy, vollständige Python-Prüfungen und unabhängiges Review abschließen.
- [x] Zur Veröffentlichung als Ready for review abgenommen. Kein automatischer Merge.

Das Issue wird erst durch den Merge der vollständig geprüften Änderung geschlossen.
