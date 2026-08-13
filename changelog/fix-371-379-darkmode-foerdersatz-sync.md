# Darkmode Contrast & Subsidy Rate Sync (Issues #371 & #379)

- Fixed code element text contrast in dark mode on `/deployment/update/`.
- Implemented `sync_meal_signup_charges_for_camp` in `services.py` to synchronize existing un-settled meal signups and charges whenever meal price rules or subsidy rates are updated.
- Added Python unit tests (`tests/test_foerdersatz_update_sync.py` and `tests/test_deployment_update_darkmode_contrast.py`).
