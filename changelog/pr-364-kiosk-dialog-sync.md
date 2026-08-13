# Stabilize kiosk dialog transition coverage

The kiosk breakfast prebooking regression test now waits for the expected native
dialog to become the active modal before interacting with it. This preserves the
existing dialog, booking, and scroll-lock assertions while avoiding WebKit clicks
during native modal transitions.
