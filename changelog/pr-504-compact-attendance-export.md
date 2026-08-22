# Kompakter Anwesenheitsexport

- Closes #474: Der Anwesenheitsexport verwendet pro Tag die kurzen, farbunabhängig unterscheidbaren Werte `AN`, `AB` und `–` sowie konsistente grüne, rote und graue Statusfarben.
- Eine eigene Legende erklärt die Statuswerte; Personen bleiben zeilenweise und Tage spaltenweise angeordnet.
- Closes #500: Eine feste Spalte `Typ` unterscheidet Hauptteilnehmer, Kinder und Begleitpersonen auch bei identischen Namen eindeutig.
- Closes #501: Die Legende beschreibt `–` ausschließlich als „Außerhalb des Aufenthaltszeitraums“; fehlende Markierungen innerhalb des Aufenthalts bleiben `AB`.
- Closes #502: Das Anwesenheitsblatt druckt im Querformat auf eine Seite Breite, mit unbegrenzter Seitenhöhe, exaktem Datenbereich und wiederholten Kopf- und Identitätsspalten.
- Closes #503: Direkte Teilnehmer werden anhand ihrer vorhandenen Kind-/Begleitpersonen-Flags typisiert; bei beiden Flags hat die Kind-Klassifikation Vorrang.
