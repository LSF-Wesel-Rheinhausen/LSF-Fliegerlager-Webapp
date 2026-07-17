---
type: "query"
date: "2026-06-01T13:37:42.789136+00:00"
question: "Why does Participant connect Billing Forms Admin to Participant Import, Export Role Commands, Test Factories, Auth Permissions?"
contributor: "graphify"
source_nodes: ["Participant", "importers.py", "exporters.py", "forms.py", "admin.py", "ParticipantFactory", "UserFactory"]
---

# Q: Why does Participant connect Billing Forms Admin to Participant Import, Export Role Commands, Test Factories, Auth Permissions?

## Answer

Participant is a cross-community bridge because graphify connects the core model at src/billing/models.py:L43 directly to admin/forms, importers, exporters/services/views, and test factories. Extracted edges link it to admin.py, forms.py, importers.py, exporters.py, services.py, signals.py, and views.py; inferred edges link it to ParticipantFactory/UserFactory and several form/admin classes. The strongest actionable trace is Participant -> importers.py/ImportRow for Participant Import, Participant -> exporters.py/services.py/views.py for export and service flow, Participant -> admin.py/forms.py for Billing Forms Admin, and Participant -> ParticipantFactory/UserFactory for tests/auth-adjacent factory setup. Caveat: many class-level edges are INFERRED, so use this trace as navigation and verify concrete behavior in source before changing contracts.

## Source Nodes

- Participant
- importers.py
- exporters.py
- forms.py
- admin.py
- ParticipantFactory
- UserFactory
