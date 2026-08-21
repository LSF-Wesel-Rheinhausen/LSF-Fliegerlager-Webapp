# Positionsauswertung für Administratoren

- Ergänzt eine Auswertungsseite je Lager unter `camps/<id>/auswertung/`, erreichbar über die Lagerübersicht und nur für Administratoren.
- Zeigt Buchungen je Artikel, gruppiert nach Art und Beschreibung, mit Anzahl, Gesamtmenge und Summe; gelöschte Buchungen bleiben unberücksichtigt.
- Zeigt Abendessen und Frühstück gesamt, aufgeschlüsselt nach Variante; zurückgenommene Essensbuchungen zählen nicht mit.
- Zeigt anwesende Personen pro Lagertag anhand von An- und Abreisedatum; Familienmitglieder zählen einzeln und greifen ohne eigene Daten auf den Zeitraum des Zahlungskontos zurück.
- Weist die Anwesenheitstage gesamt aus: Zahlungskonten mit den tatsächlichen Nächten, ersatzweise den gebuchten, Familienmitglieder über ihren eigenen Zeitraum.
- Neue Testabdeckung in `tests/test_position_report.py` für alle Kennzahlen sowie Sortierung, Lagerabgrenzung, archivierte Teilnehmer, inaktive Familienmitglieder, fehlende Datumsangaben und die Rechtevergabe.
