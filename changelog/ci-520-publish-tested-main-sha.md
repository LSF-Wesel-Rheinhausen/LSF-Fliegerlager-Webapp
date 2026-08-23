# Publish tested main SHA

- Build and validate application and updater images for pull requests without publishing.
- Publish only after the successful stable CI workflow for the exact trusted main SHA.
- Abort stale publication runs when `main` moves and retain isolated app/updater BuildKit caches.

Closes #520
Closes #553
