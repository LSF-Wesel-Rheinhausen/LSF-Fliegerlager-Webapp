# Issue #357: Rechtliche Seiten und Footer-Verlinkung

**Status:** Plan; die Implementierung ist noch nicht erfolgt.
**Issue:** Closes #357

## Ziel und Umfang

Admin- und Kiosk-Oberflächen erhalten den Footer-Text **„Built with love by Jan Sellerbeck 🦫“** sowie getrennte Links zu Impressum und Datenschutz. Auf Desktop stehen die Links im Footer, auf Mobilgeräten im jeweiligen Admin- und Kiosk-Menü. Beide Kiosk-Modi verwenden dieselben globalen Rechtsseiten.

Die zwei globalen Seiten werden in der Datenbank als Klartext gepflegt. Ausschließlich globale Admins dürfen den Inhalt bearbeiten; der Editor bietet Vorschau, Änderungszeitpunkt und einen Hinweis, wenn Inhalte fehlen. Es werden keine realen Betreiberangaben oder Rechtstexte in Repository, Fixtures, Changelog, Logs oder Screenshots aufgenommen.

Der Seitenaufruf ist nur mit gültigem bestehenden Lager-PIN-Zugriff oder als tatsächlicher globaler Admin möglich. Er nutzt die vorhandene Kiosk-Cookie-Signatur, Generation, Ablauf- und Widerrufsprüfung sowie bestehende PIN-Challenge- und Recovery-Logik. Ein beliebig angemeldetes Konto und öffentliche Allowlist-Ausnahmen reichen nicht. Die Inhalte werden als escaped Klartext ausgegeben; Antworten sind privat und nicht öffentlich cachebar.

## Umsetzung und Abnahme

- [ ] Bestehende globale Admin-Berechtigung, Kiosk-Zugriffsprüfung und PIN-Challenge-/Recovery-Routen wiederverwenden; keine parallele Authentifizierung einführen.
- [ ] Zwei globale Datenbankinhalte für Impressum und Datenschutz mit sicherem Leerzustand und Änderungszeitpunkt ergänzen.
- [ ] Admin-only Editor mit Eingabe als Klartext, Vorschau, Zeitstempel und Fehlend-Inhalt-Hinweis umsetzen.
- [ ] Gemeinsame Rechtsseiten für Admin, privaten Kiosk und zentralen Kiosk bereitstellen; Zugriff nur für gültigen Camp-PIN-Zugriff oder tatsächliche globale Admins.
- [ ] Ausgabe sicher escapen, Zeilenumbrüche lesbar darstellen und private Cache-Header setzen; Inhalte niemals in Logs oder Beispieldaten übernehmen.
- [ ] Links und Footer-Text in Desktop-Footer sowie mobilen Admin- und Kiosk-Menüs ergänzen.
- [ ] Tests für Admin-Berechtigung, gültigen/abgelaufenen/widerrufenen PIN-Zugriff, beliebig angemeldete Nicht-Admins, beide Kiosk-Modi, fehlende Inhalte, Escaping und private Cache-Header ergänzen.
- [ ] E2E-Tests für Editor/Vorschau und Links auf Desktop und Mobilgeräten ergänzen.
- [ ] Abnahme: PIN-Widerruf und -Ablauf entziehen den Zugriff; Nicht-Admins können weder Inhalte bearbeiten noch Rechtsseiten ohne gültigen Kiosk-Zugriff lesen.

## Nicht-Ziele

Keine Veröffentlichung oder Erstellung konkreter rechtlicher Inhalte und keine Speicherung realer Betreiberangaben im Quellcode.

## Abschluss

- [ ] Changelog und relevante Dokumentation ergänzen.
- [ ] Ruff, Django-Checks, Migrationsabgleich, mypy, vollständige Python- und Browserprüfungen ohne lokales Docker abschließen.
- [ ] Unabhängiges Review abschließen; danach PR auf Ready for review setzen. Kein automatischer Merge.

Dieser Draft dokumentiert zunächst nur den Plan. Das Issue wird erst durch den Merge der vollständig implementierten und geprüften Änderung geschlossen.
