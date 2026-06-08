# Dienstpläne und Kiosk-Dienste

Dieses Feature erweitert die LSF Fliegerlager Webapp um ein umfassendes System für Dienstpläne. 

- **Dienstvorlagen:** Über das Admin-Interface können tägliche Vorlagen für Dienste (z. B. Spüldienst, Küchendienst) angelegt werden. Diese definieren Startzeit, Endzeit und die Anzahl der benötigten Personen. Es können auch tageweise Ausnahmen definiert werden.
- **Kiosk-Integration:** Im Kiosk sehen die Teilnehmer nun nicht nur ihre Essensbestellungen, sondern auch ihre eingeteilten und offenen Dienste.
- **Dienste übernehmen:** Offene Dienste können von den Teilnehmern selbst im Kiosk übernommen werden.
- **Dienste tauschen:** Teilnehmer können ihre zugeteilten Dienste zum Tausch anbieten. Andere Teilnehmer können diese dann per Mausklick übernehmen.
- **Fortschritt:** Es wird ein visuell aufbereiteter Fortschrittsbalken im Kiosk und im Admin-Dashboard angezeigt, um den Erfüllungsgrad der Pflichtdienste pro Teilnehmer hervorzuheben.
- **E2E Tests:** Die neuen Flows werden über die Playwright CI-Pipeline abgedeckt.
