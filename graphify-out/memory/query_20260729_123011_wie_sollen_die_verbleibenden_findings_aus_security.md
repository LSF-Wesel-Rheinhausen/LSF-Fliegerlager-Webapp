---
type: "query"
date: "2026-07-29T12:30:11.842662+00:00"
question: "Wie sollen die verbleibenden Findings aus Security-Audit #233 umgesetzt werden?"
contributor: "graphify"
source_nodes: ["_participant_historic_settlements()", "_kiosk_checkin_participants()", "ParticipantPin", "ParticipantFamilyMemberPin", "safe_csv_cell()", "MealBookingForm", "user_role()"]
---

# Q: Wie sollen die verbleibenden Findings aus Security-Audit #233 umgesetzt werden?

## Answer

Stand nach den PRs #234, #238, #243, #244 und #245: H-1, H-2, H-3, M-1, M-5, M-7, B-3 und B-5 sind vollständig behoben; M-2 ist nur teilweise entschärft; offen sind M-3, M-4, M-6, B-1, B-2, B-4, B-6, B-7, B-8, B-9 und B-10. Empfohlene Umsetzung in sieben kleinen Pull Requests: (1) M-3 und M-6 als Kiosk-Identitätsgrenze: Rechnungen und Check-in-Änderungen nur für den exakt authentifizierten Teilnehmerdatensatz und dessen ausdrücklich eigene Begleiter; Namens-, E-Mail- und Buchungslink-Fallbacks aus Autorisierungsentscheidungen entfernen. Falls ein lagerübergreifendes Rechnungsarchiv fachlich erforderlich ist, dafür später eine explizite dauerhafte PersonIdentity-Verknüpfung einführen und niemals automatisch nur nach Name oder E-Mail zusammenführen. (2) M-2: progressive kontobezogene PIN-Sperren, zusätzliche datenbankgestützte Client-Drosselung mit datensparsamem Schlüssel sowie strukturierte Security-Ereignisse; stärkere PIN-Regeln für neue und zurückgesetzte PINs gestuft einführen, weil bestehende Hashes nicht auf ihre Länge geprüft werden können. (3) M-4: eine gemeinsame XLSX-Zellabsicherung für alle nutzergesteuerten Werte verwenden und Formelpräfixe als Text speichern; exportierte Workbooks erneut laden und Zelltyp sowie exakten Inhalt testen. (4) B-1 und B-2: den Legacy-Attendance-Pfad an dieselbe validierte, atomare Check-in-Logik anbinden, Lagergrenzen und Reihenfolge prüfen und booked_nights konsistent aktualisieren. (5) B-7 und B-8: Importstatus ausschließlich gegen erlaubte Werte validieren und MealBookingForm bei fehlender oder ungültiger Lagerkonfiguration geschlossen ablehnen. (6) B-4 und B-6: CSP-Nonce für die Schichtverwaltung ergänzen und Nutzer ohne Rolle ausdrücklich als unzugeordnet statt als Bearbeiter anzeigen. (7) B-9 und B-10: Deployment-Token als Bytes vergleichen und leere Notification-Kategorien vor dem Indexzugriff behandeln. Jeder Pull Request erhält fokussierte Fehlerfalltests, die vollständigen vorgeschriebenen Prüfungen, einen Changelog-Eintrag, ein Graphify-Update sowie den Draft-PR-, CI- und Review-Loop. Als nächster Schritt wird PR 1 empfohlen; vor dessen Umsetzung ist nur die Produktentscheidung nötig, ob der Verlust lagerübergreifender Rechnungsanzeige akzeptiert wird oder eine explizite PersonIdentity sofort mitgebaut werden soll.

## Source Nodes

- _participant_historic_settlements()
- _kiosk_checkin_participants()
- ParticipantPin
- ParticipantFamilyMemberPin
- safe_csv_cell()
- MealBookingForm
- user_role()
