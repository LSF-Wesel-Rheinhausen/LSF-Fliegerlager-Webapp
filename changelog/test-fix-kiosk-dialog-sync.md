# Stabilize kiosk dialog transition coverage

The kiosk breakfast prebooking regression test now waits for the reverse native
dialog transition to expose the food dialog before interacting with it. This
preserves the existing dialog, booking, and scroll-lock assertions while
avoiding WebKit clicks during the native modal teardown window.
