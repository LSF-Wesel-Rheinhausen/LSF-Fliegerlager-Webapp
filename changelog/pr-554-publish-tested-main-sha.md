# PR #554: Publish tested main SHA

- Build and validate application and updater images for pull requests without publishing.
- Publish only after the successful stable CI workflow for the exact trusted main SHA.
- Publish immutable SHA tags first and promote `latest` only after both image builds and
  a final main-SHA race check.
- Abort stale publication runs when `main` moves and retain isolated app/updater BuildKit caches.

Closes #520
Closes #553
