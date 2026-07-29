---
type: "audit_status"
date: "2026-07-29T12:10:40.792130+00:00"
question: "Welche Findings aus Security-Audit Issue 233 sind nach PR 245 behoben?"
contributor: "graphify"
source_nodes: ["CampKioskAccess", "KioskAccessMiddleware", "CampKioskRegistrationAttempt", "ParticipantPin", "kiosk_home()"]
---

# Q: Welche Findings aus Security-Audit Issue 233 sind nach PR 245 behoben?

## Answer

Vollständig behoben sind H-1 durch PR 234, H-2 durch PR 245, H-3 durch PR 243, M-1 als öffentliche Enumeration durch PR 244, sowie M-5, M-7 und B-3 durch PR 245. M-2 ist durch den vorgelagerten, gedrosselten Lagerzugang nur teilweise entschärft; die persönliche PIN-Sperre bleibt bei fünf Versuchen pro fünf Minuten ohne Eskalation. Offen bleiben M-3, M-4, M-6, B-1, B-2 und B-4 bis B-10. Der Status wurde in Issue 233 dokumentiert: https://github.com/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp/issues/233#issuecomment-5117539124

## Source Nodes

- CampKioskAccess
- KioskAccessMiddleware
- CampKioskRegistrationAttempt
- ParticipantPin
- kiosk_home()
