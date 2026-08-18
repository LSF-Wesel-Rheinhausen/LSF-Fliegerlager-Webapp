# Dienstbeschreibungen im Dienstplan

## Zusammenfassung

Teilnehmer erhalten auf jeder Dienstkarte einen Info-Button mit den Aufgaben des jeweiligen Dienstes. Admins und Bearbeiter können Beschreibungstexte an täglichen Vorlagen sowie an einzelnen Diensten pflegen.

## Geänderte Bereiche

- Dienstvorlagen und einzelne Dienste unterstützen mehrzeilige Beschreibungstexte.
- Die Massengenerierung übernimmt die Vorlagenbeschreibung nur für neu angelegte Dienste; individuelle Beschreibungen vorhandener Dienste bleiben bei wiederholter Generierung erhalten.
- Offene Dienste, eigene Dienste und Tauschangebote zeigen dieselbe Info-Funktion. Leere Beschreibungen verwenden einen neutralen Fallback; HTML und Markdown werden nicht interpretiert.
- Nutzer-, Admin-, Architektur-, Betriebs- und Template-Dokumentation wurde ergänzt.

## Tests

- TDD: Die neuen Beschreibungs-, Generierungs-, Fallback- und Escaping-Tests wurden zunächst rot ausgeführt und schlugen erwartungsgemäß an der fehlenden Funktion fehl.
- Danach wurden Backend- und Browserfunktion implementiert; die fokussierten Pytest- und Playwright-Tests laufen grün.
- Die E2E-Prüfung deckt Info-Dialog, Schließen per Escape, Fokus-Rückgabe und sichere Darstellung von Sonderzeichen ab.

## Offene Punkte

Keine.
