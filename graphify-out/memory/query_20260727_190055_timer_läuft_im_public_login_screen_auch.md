---
type: "query"
date: "2026-07-27T19:00:55.090944+00:00"
question: "timer läuft im public login screen auch"
contributor: "graphify"
outcome: "useful"
source_nodes: ["kiosk_login()", "_kiosk_context()", "test_private_kiosk_pin_setup_does_not_use_inactivity_logout_timer()"]
---

# Q: timer läuft im public login screen auch

## Answer

Expanded from original query via graph vocab: [timer, public, login, session, countdown, inactivity, kiosk, logout, auth, anonymous, screen]. The traversal ties kiosk_login() and _kiosk_context() in src/billing/views.py to the central kiosk inactivity logout, while existing tests preserve the timer for authenticated central sessions and omit it for private flows. The minimal fix is a login-specific kiosk_autologout=False override, leaving authenticated central pages unchanged.

## Outcome

- Signal: useful

## Source Nodes

- kiosk_login()
- _kiosk_context()
- test_private_kiosk_pin_setup_does_not_use_inactivity_logout_timer()