# Dienstpläne im Kiosk (PR 52)

Dieses Feature ergänzt die Dienstplan-Funktionalität für Teilnehmer im Kiosk.
- Teilnehmer können auf dem Kiosk-Dashboard ihre Dienst-Statistik sehen (erfüllte vs. Pflicht-Dienste).
- Teilnehmer können sich über einen separaten Dialog im Kiosk in offene Dienste eintragen.
- Teilnehmer können sich aus Diensten wieder austragen, sofern diese in der Zukunft liegen.
- **Marktplatz-Logik**: Teilnehmer können bereits übernommene Dienste zum Tausch anbieten. Andere Teilnehmer können angebotene Dienste übernehmen. Freie Plätze in Diensten werden dabei bevorzugt vor Tauschangeboten besetzt.
- Entsprechende Backend-Tests wurden hinzugefügt.
