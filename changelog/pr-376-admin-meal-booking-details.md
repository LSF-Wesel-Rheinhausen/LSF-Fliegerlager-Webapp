# Admin-Details für Essensbuchungen (Closes #365, #366)

- Die Admin-Essensübersicht trennt Caterer-Abendessen und Frühstücksvorbestellungen.
- Tagesdetails zeigen Zielperson, Zahlungskonto beziehungsweise Guardian, Variante und Status.
- Frühstück wird je Tag und Variante mit aktiven und zurückgenommenen Buchungen ausgewiesen.
- Detaildialoge zeigen die exakte Gesamtzahl, bewahren Companion-Zielidentitäten und sind für mobile
  Ansichten mit langen Namen zugänglich.

## Verifikation

- Fokussierte Python- und Chromium-Playwright-Tests bestehen.
- Query-Datumsgrenzen, Guardian-/Companion-Zuordnung und HTML-Escaping sind regressionsgetestet.
