---
type: "query"
date: "2026-07-29T10:36:06.338636+00:00"
question: "Wie wurden H-2, M-5, M-7 und B-3 aus Audit #233 umgesetzt?"
contributor: "graphify"
source_nodes: ["KioskSelfEnrollmentForm", "ParticipantRegistrationApprovalForm", "CampKioskRegistrationAttempt", "ParticipantPin", "_positive_int_or_none()"]
---

# Q: Wie wurden H-2, M-5, M-7 und B-3 aus Audit #233 umgesetzt?

## Answer

PR #245 entfernt für H-2 die öffentliche Erstlogin-PIN-Vergabe und verlangt PIN plus Bestätigung bei der Selbstregistrierung; die PIN wird ausschließlich gehasht gespeichert. M-5 ergänzt ein persistentes clientbezogenes Registrierungs-Limit sowie eine ausdrückliche Admin-Prüfung der Preismerkmale und schränkt Ablehnungen auf offene Registrierungen ein. M-7 entfernt die PIN-Hash-Modelle aus dem generischen Django-Admin. B-3 validiert positive numerische Objekt-IDs vor ORM-Zugriffen und verwirft fehlerhafte Bulk-Eingaben vollständig. Lokale Volltests und sämtliche Remote-Checks des PR-Heads sind erfolgreich.

## Source Nodes

- KioskSelfEnrollmentForm
- ParticipantRegistrationApprovalForm
- CampKioskRegistrationAttempt
- ParticipantPin
- _positive_int_or_none()
