# Revocable camp access for every kiosk

- Adds a shared, hashed camp PIN before private and central kiosk business routes.
- Issues a persistent signed device cookie that is validated against the active camp and a server-side revocation generation.
- Lets admins configure the camp PIN and invalidate all issued kiosk access cookies at once.
- Rejects unauthorized writes before kiosk views run, clears stale participant sessions, and keeps protected responses out of caches.
- Covers PIN validation, rate limiting, cookie hardening, central revocation, camp reactivation, permissions, responsive UI, and PWA flows.
- Separates PIN throttling per kiosk behind explicitly trusted reverse proxies without accepting spoofed forwarding chains.
- Stores transient Django messages in the server-side session instead of a client-readable signed cookie.
- Keeps keyboard focus stable when the manual-booking dialog is closed across supported browsers.
