# Dienstpläne & Kiosk Optimierungen (PR 52)

Dieses Feature ergänzt die Dienstplan-Funktionalität für Teilnehmer im Kiosk und im Admin-Bereich.

### Kiosk
- Teilnehmer können auf dem Kiosk-Dashboard ihre Dienst-Statistik über einen komplett überarbeiteten Fortschrittsbalken sehen (dynamische Anpassung an die Pflichtdienste, verbesserter Kontrast, Glow-Effekt).
- Tauschangebote und offene Dienste zeigen nun übersichtlich an, welche anderen Teilnehmer ("Mitstreiter") ebenfalls für diesen Dienst eingetragen sind. Bei wenig Platz (z.B. auf mobilen Geräten) wird via CSS Container Queries (`@container`) automatisch zur Kurzform ("Max M.") gewechselt.
- Der Name des angemeldeten Teilnehmers steht nun immer zentriert im Header und wird mit einer von mehreren zufälligen Begrüßungen kombiniert.
- Teilnehmer können sich aus Diensten wieder austragen oder diese zum Tausch anbieten.

### Admin-Interface
- Es wurde eine eigene Ansicht ("Tägliche Vorlagen verwalten") für das Management der täglichen Dienstvorlagen im Frontend hinzugefügt. Der Umweg über das Django-Admin-Backend entfällt.
- Administratoren können Vorlagen anlegen, bearbeiten, deaktivieren und löschen. Ein Button ermöglicht es, aus den aktiven Vorlagen automatisch die Dienste für den gesamten Lagerzeitraum zu generieren.
- In der Lager-Auswertung (Dashboard) gibt es nun ebenfalls ein neu gestaltetes Ring-Diagramm (conic-gradient) für den Lager-Fortschritt mit verbessertem Tiefen-Kontrast.

### Tests
- Die E2E Playwright-Tests (`fliegerlager.spec.js`) wurden an den neuen Frontend-Flow für die Vorlagen-Verwaltung angepasst.
- Python Unit-Tests für die Vorlagenverwaltung und die Kiosk-Logik decken die neu geschriebenen Views ab.
