# Harden kiosk registration and object actions

- Moves personal PIN assignment into kiosk self-registration and requires an administrator to verify price-relevant participant attributes before approval.
- Requires guardians to assign companion PINs and removes the unauthenticated first-login PIN setup routes.
- Prevents companion sessions from managing the guardian's family members or their PINs.
- Persistently rate-limits kiosk self-registration per camp access and privacy-preserving client key.
- Removes personal PIN hash models from the generic Django admin.
- Validates submitted object identifiers before database access so malformed kiosk and shift requests fail without side effects.
- Gives login and self-registration PIN fields unique accessible identifiers.
- Updates kiosk guidance, operational documentation, and regression coverage for the revised PIN lifecycle.
