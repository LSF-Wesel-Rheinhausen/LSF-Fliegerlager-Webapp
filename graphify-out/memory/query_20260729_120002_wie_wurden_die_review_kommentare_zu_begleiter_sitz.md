---
type: "implementation"
date: "2026-07-29T12:00:02.347101+00:00"
question: "Wie wurden die Review-Kommentare zu Begleiter-Sitzungen in PR 245 behoben?"
contributor: "graphify"
source_nodes: ["kiosk_home()", "ParticipantFamilyMember", "test_companion_cannot_create_another_companion_for_guardian()", "test_companion_cannot_deactivate_guardians_family_member()", "test_companion_does_not_see_family_management()"]
---

# Q: Wie wurden die Review-Kommentare zu Begleiter-Sitzungen in PR 245 behoben?

## Answer

Begleiter-Sitzungen dürfen keine Familienmitglieder mehr erstellen, deaktivieren oder deren PIN ändern. kiosk_home blockiert alle drei Familienaktionen zentral mit HTTP 403, bevor die Aktion ausgeführt wird; die gesamte Familienverwaltung wird für Begleiter außerdem nicht gerendert. Hauptteilnehmer behalten die bestehenden Verwaltungsabläufe. Regressionstests decken gefälschte Erstellungs- und Deaktivierungs-POSTs sowie die ausgeblendete Oberfläche ab.

## Source Nodes

- kiosk_home()
- ParticipantFamilyMember
- test_companion_cannot_create_another_companion_for_guardian()
- test_companion_cannot_deactivate_guardians_family_member()
- test_companion_does_not_see_family_management()
