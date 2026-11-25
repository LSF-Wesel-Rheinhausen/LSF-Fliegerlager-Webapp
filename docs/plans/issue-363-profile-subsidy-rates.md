# Issue #363: Hilfs- und Berufssatz im Jugendgruppenprofil anzeigen

**Status:** Plan; die Implementierung ist noch nicht erfolgt.
**Issue:** Closes #363

## Ziel und Umfang

Teilnehmende einer Jugendgruppe sehen im eigenen Kiosk-Profil ihre gespeicherten Hilfs- und Berufssätze sowie die daraus berechnete effektive Förderung. Die effektive Förderung wird je anwendbarer Preisregel mit dem bestehenden Berechnungsservice ermittelt, einschließlich dessen Deckelung. Ein Satz von 0 ist ein gültiger, sichtbarer Wert und darf nicht wie ein fehlender Wert behandelt werden.

Die Anzeige ist rein lesend. Sie verwendet die bestehenden Berechtigungen und Berechnungen, verändert keine Preise oder Buchungen und zeigt keine Werte oder Identität anderer Familienmitglieder an. Die Profil- und Finanzanzeige bleibt auch dann verfügbar, wenn Buchungsmodule aus Issue #595 deaktiviert sind.

## Umsetzung und Abnahme

- [ ] Bestehenden Berechnungsservice und eigene Profilansicht verwenden; keine parallele Berechnungslogik einführen.
- [ ] Hilfssatz, Berufssatz und effektive Förderung für jede anwendbare Preisregel verständlich und lokalisiert darstellen.
- [ ] Nullwerte ausdrücklich anzeigen; bei nicht anwendbarer Preisregel oder Nicht-Jugendgruppe die vorhandene Fachlogik respektieren.
- [ ] Familien-/Partneransichten auf Identitätstrennung prüfen; keine Fördersätze anderer Personen in das eigene Profil übernehmen.
- [ ] Django-Tests für Berechnungsservice, Satz 0, Deckelung, mehrere Preisregeln und Berechtigungs-/Identitätsgrenzen ergänzen.
- [ ] E2E-Test für die eigene Profilanzeige sowie für die Abwesenheit fremder Familienwerte ergänzen.
- [ ] Abnahme: Anzeige entspricht dem Service je Preisregel und bleibt lesend; Buchungsmodul-Schalter ändern ihre Verfügbarkeit nicht.

## Nicht-Ziele

Keine Eingabe oder Änderung von Fördersätzen durch Teilnehmende und keine Änderung an Preisregeln, Buchungen oder Abrechnungen.

## Abschluss

- [ ] Changelog und relevante Dokumentation ergänzen.
- [ ] Ruff, Django-Checks, Migrationsabgleich, mypy, vollständige Python- und Browserprüfungen ohne lokales Docker abschließen.
- [ ] Unabhängiges Review abschließen; danach PR auf Ready for review setzen. Kein automatischer Merge.

Dieser Draft dokumentiert zunächst nur den Plan. Das Issue wird erst durch den Merge der vollständig implementierten und geprüften Änderung geschlossen.
