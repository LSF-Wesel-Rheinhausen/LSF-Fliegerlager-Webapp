# Update PWA manifest language and bump cache version

- Bumps `PWA_CACHE_VERSION` to 30 to ensure devices download the updated service worker containing the `lang: "de-DE"` setting for push notifications.
- Updates the `lang` attribute in `manifest.json` from `de` to `de-DE` for consistency.
- Adds test coverage for the manifest `lang` attribute.
