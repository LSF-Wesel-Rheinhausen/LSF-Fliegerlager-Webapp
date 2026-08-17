# Graph Report - actions-pipeline  (2026-07-30)

## Corpus Check
- 300 files · ~369,873 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2560 nodes · 5607 edges · 288 communities (157 shown, 131 thin omitted)
- Extraction: 75% EXTRACTED · 25% INFERRED · 0% AMBIGUOUS · INFERRED: 1393 edges (avg confidence: 0.56)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `aeda8301`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Django Admin Integration
- Authentication and Permissions
- Django Database Models
- Repository Guidelines and Rules
- Form Handlers and Initializers
- Test Data Factories
- Database Schemas and Migrations
- Camp and Document Exporters
- CSV and Data Importers
- Package Configurations
- Application Settings and Setup
- Playwright E2E Integration Tests
- Local Testing Utility Scripts
- Developer Bootstrap Scripts
- Playwright Setup and E2E Workflows
- Brand logo and Media assets
- E2E Playwright Environment Variables
- App config initializers
- Repository Documentation
- Flatrate Database Migrations
- Playwright Configuration Settings
- Billing Application URLs
- Initial Database Migrations
- Camp Schema Evolution Migrations
- Developer Codex Cleanup Utilities
- Developer Codex Setup Utilities
- Django Core Management Script
- Developer Codex Server Starter
- Django App Command Initialization
- Billing App Commands Initializer
- Migration Package Initialization
- Custom Template Tag Initializer
- Django Config Initializer
- ASGI App Entrypoint
- WSGI App Entrypoint
- Email or Username Backend
- Meal Signup Model
- Kiosk/Billing Assets Documentation
- Kiosk Session Participant Handler
- Kiosk Participant Utility Views
- Participant Connection Memory Query
- Community 44
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92
- Community 93
- Community 94
- Community 95
- Community 96
- Community 97
- Community 98
- Community 99
- Community 100
- Community 101
- Community 102
- Community 103
- Community 104
- Community 105
- Community 106
- Community 107
- Community 108
- Community 109
- Community 110
- Community 111
- Community 112
- Community 113
- Community 114
- Community 115
- Community 116
- Community 117
- Community 118
- Community 119
- Community 120
- Community 121
- Community 122
- Community 123
- Community 125
- Community 126
- Community 127
- Community 129
- Community 130
- Community 131
- Community 132
- Community 133
- Community 134
- Community 135
- Community 136
- Community 137
- Community 138
- Community 139
- Community 140
- Community 141
- Community 142
- Community 143
- Community 144
- Community 145
- Community 146
- Community 147
- Community 148
- Community 149
- Community 150
- Community 151
- Community 152
- Community 153
- Community 154
- Community 155
- Community 156
- Community 157
- Community 158
- Community 159
- Community 160
- Community 161
- Community 162
- Community 163
- Community 164
- Community 165
- Community 166
- Community 167
- Community 168
- Community 169
- Community 170
- Community 171
- Community 172
- Community 173
- Community 174
- Community 175
- Community 176
- Community 177
- Community 178
- Community 179
- Community 180
- Community 181
- Community 182
- Community 183
- Community 184
- Community 185
- Community 186
- Community 187
- Community 188
- Community 189
- Community 190
- Community 191
- Community 192
- Community 193
- Community 194
- Community 195
- Community 196
- Community 197
- Community 198
- Community 199
- Community 200
- Community 201
- Community 202
- Community 203
- Community 204
- Community 205
- Community 206
- Community 207
- Community 208
- Community 209
- Community 210
- Community 211
- Community 212
- Community 213
- Community 214
- Community 215
- Community 216
- Community 217
- Community 218
- Community 219
- Community 220
- Community 221
- Community 222
- Community 223
- Community 224
- Community 225
- Community 226
- Community 228
- Community 229
- Community 231
- Community 232
- Community 234
- Community 235
- Community 236
- Community 237
- Community 238
- Community 239
- Community 247
- Community 248
- test_actions_workflows.py
- create_manual_charge
- Community 268
- test_user_management.py
- build_settlement_backup_staging
- kiosk_shifts
- Community 278
- Community 287
- Community 289
- Community 335
- Community 338
- Community 340
- Community 342
- Community 350
- Community 352
- Community 353
- Community 369
- Community 370
- bytes

## God Nodes (most connected - your core abstractions)
1. `SuperUserFactory` - 103 edges
2. `Camp` - 97 edges
3. `ParticipantFactory` - 94 edges
4. `Participant` - 85 edges
5. `UserFactory` - 74 edges
6. `Charge` - 69 edges
7. `ParticipantFamilyMember` - 66 edges
8. `DailySettlementBackupSettings` - 65 edges
9. `PriceRule` - 64 edges
10. `Expense` - 64 edges

## Surprising Connections (you probably didn't know these)
- `test_shared_camp_pin_accepts_only_six_to_twelve_digits()` --calls--> `KioskCampAccessForm`  [INFERRED]
  tests/test_kiosk_access.py → src/billing/forms.py
- `AuthorizedKioskClient` --uses--> `Camp`  [INFERRED]
  tests/conftest.py → src/billing/models.py
- `test_backup_staging_contains_exports_and_manifest()` --calls--> `build_settlement_backup_staging()`  [INFERRED]
  tests/test_daily_settlement_backups.py → src/billing/daily_settlement_backups.py
- `test_daily_backup_creates_one_daily_backup_run()` --calls--> `run_due_daily_settlement_backup()`  [INFERRED]
  tests/test_daily_settlement_backups.py → src/billing/daily_settlement_backups.py
- `test_daily_backup_does_not_run_before_configured_time()` --calls--> `run_due_daily_settlement_backup()`  [INFERRED]
  tests/test_daily_settlement_backups.py → src/billing/daily_settlement_backups.py

## Import Cycles
- 1-file cycle: `src/billing/services.py -> src/billing/services.py`
- 1-file cycle: `src/billing/exporters.py -> src/billing/exporters.py`
- 1-file cycle: `src/billing/templatetags/billing_format.py -> src/billing/templatetags/billing_format.py`

## Communities (288 total, 131 thin omitted)

### Community 0 - "Django Admin Integration"
Cohesion: 0.04
Nodes (75): CampForm, ParticipantRegistrationApprovalForm, Return the default noon cutoff when the form field is omitted., Require an explicit administrative decision on price-relevant attributes., Camp, Participant, _accepted_booking_links(), approve_participant_registration() (+67 more)

### Community 2 - "Authentication and Permissions"
Cohesion: 0.14
Nodes (42): BookingAuditLogAdmin, CampAdmin, ChargeAdmin, DailySettlementBackupLogAdmin, DailyShiftExceptionInline, DailyShiftTemplateAdmin, MealOrderAdmin, MealPlanEntryAdmin (+34 more)

### Community 3 - "Django Database Models"
Cohesion: 0.10
Nodes (11): AutheliaSSOMiddleware, HttpRequest, HttpResponse, str, Create a Django session from a trusted Authelia email header when enabled., Attach application-wide browser security headers to dynamic and static responses, Return the CSP value for a request-scoped nonce., SecurityHeadersMiddleware (+3 more)

### Community 4 - "Repository Guidelines and Rules"
Cohesion: 0.05
Nodes (45): DailySettlementBackupLog, DailySettlementBackupSettings, build_settlement_backup_staging(), _claim_daily_backup_log(), Any, bool, Camp, Path (+37 more)

### Community 5 - "Form Handlers and Initializers"
Cohesion: 0.09
Nodes (46): PasskeyCredential, Hash a new shared PIN and invalidate every previously issued cookie., Rotate the generation used to validate every issued access cookie., _audit_event(), _json_request_body(), passkey_authentication_options(), passkey_authentication_verify(), passkey_delete() (+38 more)

### Community 6 - "Test Data Factories"
Cohesion: 0.12
Nodes (21): UserFactory, test_user_can_authenticate_with_email(), str, test_authenticated_navigation_links_to_passkey_management_only_when_enabled(), test_authentication_rejects_a_challenge_timestamp_from_the_future(), test_authentication_verifies_the_credential_and_updates_its_counter(), test_authentication_verify_endpoint_creates_a_django_session(), test_inactive_user_cannot_authenticate_with_a_stored_passkey() (+13 more)

### Community 7 - "Database Schemas and Migrations"
Cohesion: 0.09
Nodes (30): computedHash, skillPath, source, sourceType, computedHash, skillPath, source, sourceType (+22 more)

### Community 9 - "CSV and Data Importers"
Cohesion: 0.12
Nodes (71): AuthenticationForm, LoginView, SetPasswordForm, CampFlatRateSettingsForm, CampKioskAccessAdminForm, ChargeForm, DailySettlementBackupSettingsForm, DailyShiftTemplateForm (+63 more)

### Community 10 - "Package Configurations"
Cohesion: 0.15
Nodes (36): LegacyPersistence, _chown_tree(), _copy_source(), _directory_has_content(), LegacyPersistence, main(), migrate_persistence(), MigrationResult (+28 more)

### Community 11 - "Application Settings and Setup"
Cohesion: 0.10
Nodes (49): EmailBatch, EmailDeliveryResult, Any, int, object, queue_information_email_batch(), queue_settlement_email_batch(), Queue a manually confirmed information email once per normalized address. (+41 more)

### Community 12 - "Playwright E2E Integration Tests"
Cohesion: 0.24
Nodes (18): build_settlement_line(), calculate_participant_settlement(), charge_audit_snapshot(), create_booking_audit_log(), default_charge_lines(), drink_charge_lines(), manual_charge_lines(), money() (+10 more)

### Community 13 - "Local Testing Utility Scripts"
Cohesion: 0.06
Nodes (18): Any, date, Require a confirmed PIN when the family member receives a login., Return the stable dynamic field name for a meal date., Persist non-empty descriptions and remove cleared menu entries., Limit selectable dates to the participant's configured camp days., Return unique selected camp dates in chronological order., Persist the user account without assigning groups.          Args:             co (+10 more)

### Community 14 - "Developer Bootstrap Scripts"
Cohesion: 0.10
Nodes (15): addDays(), createCamp(), dateInputValue(), { expect, test }, { isBenignPageRequestFailure, requestFailureDetails }, { KIOSK_ACCESS_PIN, configureCampKioskAccess, openKiosk }, loginAsAdmin(), setupFirstAdmin() (+7 more)

### Community 15 - "Playwright Setup and E2E Workflows"
Cohesion: 0.13
Nodes (19): admin_interface_contacts(), AdminInterfaceContact, approve_shared_expense(), _notify_expense_status_by_id(), _phone_href(), Any, Expense, int (+11 more)

### Community 16 - "Brand logo and Media assets"
Cohesion: 0.11
Nodes (19): extract_stack_env(), limit_output(), PortainerAPIError, PortainerClient, int, Shorten process output for UI-safe diagnostics., Small Portainer API client scoped to one endpoint and stack., Return the Portainer TLS context, or None for default certificate verification. (+11 more)

### Community 17 - "E2E Playwright Environment Variables"
Cohesion: 0.12
Nodes (24): admin_guide(), booking_audit_restore(), charge_delete(), deployment_daily_backup_settings(), deployment_update(), deployment_update_check(), deployment_update_install(), kiosk_root() (+16 more)

### Community 18 - "App config initializers"
Cohesion: 0.10
Nodes (50): PushSubscription, Store one browser push capability for an admin or participant device., _category_selection(), _device_name(), _device_payload(), _endpoint_fingerprint(), _json_payload(), kiosk_notification_preferences() (+42 more)

### Community 19 - "Repository Documentation"
Cohesion: 0.12
Nodes (17): _freeze_meal_lock_time(), test_kiosk_books_meal_for_linked_participant_on_linked_account(), test_kiosk_books_multiple_meal_dates_and_targets_atomically(), test_kiosk_creates_family_member_and_books_meal_on_guardian(), test_kiosk_meal_booking_dialog_keeps_child_only_price_day_selectable(), test_kiosk_meal_booking_dialog_shows_all_camp_days_with_prices(), test_kiosk_meal_day_detail_opens_booking_for_the_selected_date(), test_kiosk_meal_signup_child_breakfast_override() (+9 more)

### Community 20 - "Flatrate Database Migrations"
Cohesion: 0.15
Nodes (20): ImportRow, normalize_row(), parse_bool(), parse_date(), parse_decimal(), parse_int(), _peek(), preview_participants() (+12 more)

### Community 21 - "Playwright Configuration Settings"
Cohesion: 0.18
Nodes (14): _kiosk_operation_redirect(), _kiosk_route(), kiosk_shared_expense_request(), kiosk_shifts(), _notify_shift_exchange_by_id(), _post_camp_kiosk_operation_redirect(), _pre_camp_kiosk_operation_redirect(), Return the named route for a kiosk page in the active device mode. (+6 more)

### Community 22 - "Billing Application URLs"
Cohesion: 0.09
Nodes (22): CampFactory, test_camp_flat_rate_settings_form_updates_and_creates_rules(), test_camp_form_renders_dates_in_iso_format(), test_camp_form_saves_meal_booking_cutoff_time(), test_deleting_active_camp_activates_remaining_camp(), test_kiosk_login_form_lists_companions_but_not_children(), test_kiosk_login_form_only_lists_non_archived_participants_from_active_camp(), test_kiosk_login_form_starts_empty_and_sorts_targets_by_last_name() (+14 more)

### Community 24 - "Initial Database Migrations"
Cohesion: 0.10
Nodes (39): ParticipantBookingLink, ShiftAssignment, _administrative_users(), allowed_categories(), cleanup_push_messages(), generate_scheduled_notifications(), notify_booking_link(), notify_expense_status() (+31 more)

### Community 25 - "Camp Schema Evolution Migrations"
Cohesion: 0.32
Nodes (5): ABORTED_FAILURE_TEXT_PATTERNS, isBenignPageRequestFailure(), assert, { isBenignPageRequestFailure }, test

### Community 27 - "Developer Codex Setup Utilities"
Cohesion: 0.13
Nodes (5): EmailConfiguration, Store the singleton SMTP configuration managed by administrators., Validate a raw PIN and apply lockout accounting., Replace the encrypted SMTP password., Return the decrypted SMTP password.

### Community 28 - "Django Core Management Script"
Cohesion: 0.14
Nodes (9): admin_user(), _login_redirect(), test_admin_booking_restore_rejects_editor_and_allows_admin(), test_admin_charge_delete_rejects_editor_and_allows_admin(), test_admin_only_get_views_reject_anonymous_and_editor(), test_admin_pin_post_views_reject_editor_and_allow_admin(), test_admin_post_views_reject_editor_and_allow_admin(), test_editor_views_reject_anonymous() (+1 more)

### Community 29 - "Developer Codex Server Starter"
Cohesion: 0.14
Nodes (9): test_authelia_backend_rejects_inactive_user_directly(), test_authelia_header_switches_existing_session_user(), test_authelia_sso_logs_in_unique_active_user_case_insensitively(), test_authelia_sso_uses_only_configured_header(), test_disabled_authelia_sso_ignores_identity_header(), test_duplicate_authelia_email_is_rejected(), test_inactive_authelia_user_is_rejected(), test_missing_authelia_header_does_not_authenticate() (+1 more)

### Community 30 - "Django App Command Initialization"
Cohesion: 0.33
Nodes (5): Geänderte Dateien, Offene Punkte, Sichere Seitenumbrüche für Rechnungs-PDFs, Tests, Zusammenfassung

### Community 32 - "Migration Package Initialization"
Cohesion: 0.13
Nodes (32): backup_child_path(), choose_manifest_descriptor(), create_backup(), create_backup_archive(), database_dump_bytes(), fetch_image_metadata(), fetch_registry_token(), immutable_running_image() (+24 more)

### Community 33 - "Custom Template Tag Initializer"
Cohesion: 0.13
Nodes (27): _html_body(), _information_dedupe_key(), information_recipient_mapping(), InformationRecipient, normalize_recipient_email(), Camp, EmailConfiguration, SettlementRun (+19 more)

### Community 34 - "Django Config Initializer"
Cohesion: 0.18
Nodes (11): OSError, SMTPException, has_valid_recipient_email(), _is_permanent_smtp_failure(), bool, Return whether persisted application data contains a deliverable address., Return whether an SMTP failure cannot recover after a configuration update., _smtp_status_code() (+3 more)

### Community 35 - "ASGI App Entrypoint"
Cohesion: 0.06
Nodes (7): Client, test_admin_revoke_invalidates_all_issued_camp_cookies(), test_shared_camp_pin_accepts_only_six_to_twelve_digits(), test_shared_pin_rate_limit_distinguishes_clients_behind_trusted_proxy(), test_shared_pin_rate_limit_ignores_forwarded_address_from_untrusted_peer(), test_shared_pin_rate_limit_rejects_ambiguous_forwarded_chain(), test_shared_pin_rate_limit_survives_discarded_client_sessions()

### Community 37 - "WSGI App Entrypoint"
Cohesion: 0.29
Nodes (5): fs, http, { spawn }, test, { test: base, expect }

### Community 38 - "Email or Username Backend"
Cohesion: 0.15
Nodes (13): CI/CD & Automatisierung, Exporte, HTML-Dokumentation, Importformat, Lokaler Start, Projektdokumentation, Projektstruktur, Qualitäts- und Sicherheitsregeln (+5 more)

### Community 39 - "Meal Signup Model"
Cohesion: 0.15
Nodes (13): devDependencies, name, private, scripts, codex:cleanup, codex:setup, codex:start, start:e2e (+5 more)

### Community 40 - "Kiosk/Billing Assets Documentation"
Cohesion: 0.20
Nodes (10): CI/CD & Automatisierung, Docker, Dokumentation, Fliegerlager-Abrechnung, Funktionen in V1, Konfiguration, Lokale Entwicklung, Roadmap (+2 more)

### Community 41 - "Kiosk Session Participant Handler"
Cohesion: 0.25
Nodes (13): build_manifest(), changelog_title_and_body(), git_output(), last_revision_for(), int, Path, str, Run git and return stripped stdout. (+5 more)

### Community 42 - "Kiosk Participant Utility Views"
Cohesion: 0.20
Nodes (12): _activate_kiosk_mode(), _clear_kiosk_session(), kiosk_login(), kiosk_logout(), kiosk_self_register(), Render one kiosk login page with optional bound forms., Authenticate a participant in a private or central kiosk session., Handle self-registration submission from Kiosk login page. (+4 more)

### Community 43 - "Participant Connection Memory Query"
Cohesion: 0.20
Nodes (14): AgentConfigError, has_update(), parse_bool_env(), parse_database_url(), bool, str, Mask a secret while preserving enough context for diagnostics., Compare latest OCI labels with the currently running Django build metadata. (+6 more)

### Community 44 - "Community 44"
Cohesion: 0.22
Nodes (10): _is_application_admin_account(), Any, Expose whether the optional passkey login is enabled., Reject delegated administration of an existing superuser account., Edit account status and billing role for an existing user., Set a new password for an existing application user., _require_superuser_for_superuser_account(), user_edit() (+2 more)

### Community 46 - "Community 46"
Cohesion: 0.17
Nodes (13): BaseException, perform_update(), Persist updater state atomically and return the merged state., Set APP_IMAGE in Portainer and trigger a stack redeploy., Format an update error for the Django status page., Return operator guidance that does not include secrets., Install the configured APP_IMAGE through Portainer and rollback on failure., Return the current UTC timestamp in ISO-8601 format. (+5 more)

### Community 47 - "Community 47"
Cohesion: 0.21
Nodes (10): healthcheck(), page_not_found(), platform_icon(), Exception, HttpRequest, HttpResponse, JsonResponse, Report application readiness without exposing operational details. (+2 more)

### Community 48 - "Community 48"
Cohesion: 0.13
Nodes (18): BaseHTTPRequestHandler, check_update(), current_metadata_from_payload(), deployment_status(), load_state(), Any, Return the configured Portainer stack., Return APP_IMAGE from the Portainer stack variables. (+10 more)

### Community 49 - "Community 49"
Cohesion: 0.18
Nodes (10): Agent Instructions, Commands, Engineering Rules, Frontend, Git And Pull Requests, Graphify, Project Map, Scope And Precedence (+2 more)

### Community 50 - "Community 50"
Cohesion: 0.22
Nodes (7): ModelBackend, AutheliaEmailBackend, EmailOrUsernameBackend, Any, HttpRequest, str, Authenticate an existing active user from Authelia's trusted email header.

### Community 51 - "Community 51"
Cohesion: 0.18
Nodes (10): Aktuelle Findings (7. Juli 2026), Behobene Findings (Historisch), Executive Summary, Prüfungen, SEC-001: Unsichere Produktions-Fallbacks, SEC-002: Beweglicher und zeitweise kompromittierter Trivy-Action-Pin, SEC-003: Unbegrenzte Import- und PIN-Versuche, SEC-004: Selbstvergabe einer noch nicht gesetzten Kiosk-PIN (Verbleibendes Risiko) (+2 more)

### Community 53 - "Community 53"
Cohesion: 0.20
Nodes (9): DATABASE_URL, DJANGO_ALLOWED_HOSTS, DJANGO_DEBUG, DJANGO_SECRET_KEY, PASSKEY_ENABLED, PASSKEY_ORIGIN, PASSKEY_RP_ID, PASSKEY_RP_NAME (+1 more)

### Community 56 - "Community 56"
Cohesion: 0.22
Nodes (9): FileResponse, expense_receipt_download(), kiosk_current_settlement_pdf(), _kiosk_participant(), _kiosk_participant_from_session(), kiosk_settlement_pdf(), Return an uploaded expense receipt when the requester may inspect it.      Edito, Allow logged-in kiosk participants to download their own finalized settlement PD (+1 more)

### Community 57 - "Community 57"
Cohesion: 0.25
Nodes (8): Authelia Trusted-Header-SSO, Einmalige Migration bestehender Installationen, Manuelle Wartung, Manueller E-Mail-Versand, Passkey-/WebAuthn-Anmeldung, Portainer-Deployment, PWA und Web Push, Updates

### Community 58 - "Community 58"
Cohesion: 0.22
Nodes (3): test_kiosk_post_camp_renders_one_read_only_invoice_area(), test_kiosk_post_camp_renders_screen_and_settlement_archive(), test_kiosk_settlement_pdf_download_permissions()

### Community 59 - "Community 59"
Cohesion: 0.25
Nodes (7): Agent Configuration, Commits And Pull Requests, Contributing, Development Workflow, Engineering And Security Standards, Setup, Verification

### Community 60 - "Community 60"
Cohesion: 0.25
Nodes (7): Dependency Graph Audit, Empfehlung, Ergebnis, Node, Reduktionskandidaten, Runtime Python, Updater

### Community 61 - "Community 61"
Cohesion: 0.13
Nodes (32): Settlement, camp_settlement_csv(), camp_workbook_response(), csv_response(), _decimal_text(), _draw_invoice_line(), drink_entries_csv(), _format_invoice_date() (+24 more)

### Community 62 - "Community 62"
Cohesion: 0.33
Nodes (5): Abstands- und Phasenlayout bereinigt, Geänderte Dateien, Offene Punkte, Tests, Zusammenfassung

### Community 63 - "Community 63"
Cohesion: 0.33
Nodes (5): Geänderte Dateien, Kein Inaktivitäts-Timer im öffentlichen Kiosk-Login, Offene Punkte, Tests, Zusammenfassung

### Community 64 - "Community 64"
Cohesion: 0.50
Nodes (7): test-local.sh script, print_header(), print_line(), RESULTS, run_step(), test-local.sh script, STEPS

### Community 65 - "Community 65"
Cohesion: 0.12
Nodes (30): ChargeFactory, GroupFactory, PriceRuleFactory, assert_manual_charge_dialog_auto_opens(), test_admin_can_delete_booking_and_keeps_audit_log(), test_admin_can_edit_booking_and_creates_audit_log(), test_admin_can_restore_deleted_booking_from_audit_log(), test_admin_cannot_restore_deleted_booking_without_participant() (+22 more)

### Community 66 - "Community 66"
Cohesion: 0.33
Nodes (5): Geänderte Dateien, Offene Punkte, Schnellere und klarere Actions-Pipeline, Tests, Zusammenfassung

### Community 67 - "Community 67"
Cohesion: 0.33
Nodes (5): Dokumentation aktualisiert, Geaenderte Dateien, Offene Punkte, Tests, Zusammenfassung

### Community 68 - "Community 68"
Cohesion: 0.33
Nodes (5): Geaenderte Dateien, Offene Punkte, PR-Zusammenfassung: feature/auditable-booking-edit, Verifikation, Zusammenfassung

### Community 69 - "Community 69"
Cohesion: 0.33
Nodes (5): Geänderte Dateien, Kiosk-Getränkekarten ausrichten, Offene Punkte, Tests, Zusammenfassung

### Community 70 - "Community 70"
Cohesion: 0.33
Nodes (5): Geänderte Dateien, Kiosk-Familienbuchungen, Offene Punkte, Tests, Zusammenfassung

### Community 71 - "Community 71"
Cohesion: 0.33
Nodes (5): Geänderte Dateien, Offene Punkte, PR 12: Modern Web Guidance UI Refactoring, Tests, Zusammenfassung

### Community 72 - "Community 72"
Cohesion: 0.33
Nodes (5): Geänderte Dateien, Offene Punkte, PR 14: Fix E2E Script Python Path, Tests, Zusammenfassung

### Community 73 - "Community 73"
Cohesion: 0.33
Nodes (5): Geänderte Dateien, Kiosk-Layout und Gemeinschaftsausgaben, Offene Punkte, Tests, Zusammenfassung

### Community 74 - "Community 74"
Cohesion: 0.33
Nodes (5): Geänderte Dateien, Notification-Geräteverwaltung und Installationshinweise, Offene Punkte, Tests, Zusammenfassung

### Community 75 - "Community 75"
Cohesion: 0.33
Nodes (5): Geänderte Dateien, Kiosk-Buchungen mit Legacy-Datenbanken reparieren, Offene Punkte, Tests, Zusammenfassung

### Community 76 - "Community 76"
Cohesion: 0.33
Nodes (5): Informationsmails, Konfiguration, Manueller E-Mail-Versand, Rechnungen, Zustellung und Fehler

### Community 77 - "Community 77"
Cohesion: 0.33
Nodes (5): Abrechnungs-PDFs mit klarer Seitenstruktur, Geänderte Dateien, Offene Punkte, Tests, Zusammenfassung

### Community 78 - "Community 78"
Cohesion: 0.47
Nodes (5): _column_names(), Migration, Any, str, remove_legacy_charge_cancellation_columns()

### Community 79 - "Community 79"
Cohesion: 0.40
Nodes (4): Geänderte Bereiche, Playwright-CI-Cache, Tests, Zusammenfassung

### Community 80 - "Community 80"
Cohesion: 0.40
Nodes (4): Dokumentation, Screenshots und Tooling aktualisiert, Offene Punkte, Tests, Zusammenfassung

### Community 81 - "Community 81"
Cohesion: 0.40
Nodes (4): Deployment-Update-Diagnose, Geänderte Bereiche, Tests, Zusammenfassung

### Community 82 - "Community 82"
Cohesion: 0.40
Nodes (4): Geänderte Bereiche, Mobile Layout-Fixes, Tests, Zusammenfassung

### Community 83 - "Community 83"
Cohesion: 0.40
Nodes (4): Buchungen löschen, Geänderte Dateien, Tests, Zusammenfassung

### Community 84 - "Community 84"
Cohesion: 0.40
Nodes (4): Admin-Interface, Essenskalender & Speiseplanpflege (PR #113), Kiosk, Tests

### Community 85 - "Community 85"
Cohesion: 0.40
Nodes (4): Buchungsnummern, Geänderte Dateien, Tests, Zusammenfassung

### Community 86 - "Community 86"
Cohesion: 0.40
Nodes (4): Admin-Interface, Dienstpläne & Kiosk Optimierungen (PR 52), Kiosk, Tests

### Community 87 - "Community 87"
Cohesion: 0.40
Nodes (4): Geänderte Bereiche, Optimiertes Container-Deployment mit Admin-Updates, Tests, Zusammenfassung

### Community 88 - "Community 88"
Cohesion: 0.40
Nodes (4): Database / Models, Feature / Change, Kiosk Snacks and Breakfast Separation, Rationale

### Community 89 - "Community 89"
Cohesion: 0.40
Nodes (4): Aktivierung, Passkeys und WebAuthn, Recovery und Betrieb, Sicherheitsmodell

### Community 90 - "Community 90"
Cohesion: 0.50
Nodes (4): Gerätemodi, Offline-Grenzen, Push-Betrieb, PWA und Push-Benachrichtigungen

### Community 92 - "Community 92"
Cohesion: 0.06
Nodes (53): PinAttemptResult, clear_kiosk_access_cookie(), clear_kiosk_identity_session(), _is_protected_kiosk_route(), kiosk_access_from_request(), KioskAccessMiddleware, Any, HttpRequest (+45 more)

### Community 93 - "Community 93"
Cohesion: 0.26
Nodes (13): abs_value(), can_manage_meals(), can_manage_users(), is_huebers_user(), money_eur(), percent(), Any, bool (+5 more)

### Community 94 - "Community 94"
Cohesion: 0.05
Nodes (26): Action, AllocationMethod, CampAnnouncement, CampFlatDuration, CampFlatRole, CostCenter, Drink, EmailBatch (+18 more)

### Community 95 - "Community 95"
Cohesion: 0.33
Nodes (6): changelog_between_versions(), image_metadata(), normalized_changelog_entries(), Return UI-safe changelog entries from an OCI label value., Normalize OCI image metadata from Docker-like objects or dict payloads., Return changelog entries after the current build up to the latest build.

### Community 97 - "Community 97"
Cohesion: 0.50
Nodes (3): Dokumentation, Portainer SSL-Verifikation konfigurierbar (PR #114), Update-Agent

### Community 98 - "Community 98"
Cohesion: 0.50
Nodes (3): Tests, Tägliche Abrechnungshistorie und Backup-Archive, Zusammenfassung

### Community 99 - "Community 99"
Cohesion: 0.50
Nodes (3): Dienstpläne und Kiosk-Dienste (PR #53), 🌟 Neue Features & UX-Verbesserungen, 🛠️ Technische Bugfixes & Code-Qualität

### Community 100 - "Community 100"
Cohesion: 0.50
Nodes (3): Teilnehmerarchiv, Abrechnungsläufe und Docker-Betrieb, Tests, Zusammenfassung

### Community 101 - "Community 101"
Cohesion: 0.50
Nodes (3): Mobile Tabellen Scrollbar, Tests, Zusammenfassung

### Community 102 - "Community 102"
Cohesion: 0.50
Nodes (3): Answer, Q: Why does Participant connect Billing Forms Admin to Participant Import, Export Role Commands, Test Factories, Auth Permissions?, Source Nodes

### Community 105 - "Community 105"
Cohesion: 0.67
Nodes (3): Path, test_build_manifest_adds_first_parent_version(), test_docker_workflow_uses_first_parent_version()

### Community 106 - "Community 106"
Cohesion: 0.67
Nodes (3): str, test_background_workers_disable_inherited_http_healthcheck(), test_email_worker_uses_read_only_webpush_key_mount()

### Community 113 - "Community 113"
Cohesion: 0.40
Nodes (3): PasskeyCredential, Store a verified WebAuthn credential for an application user., Return the stable, non-PII WebAuthn user handle for this account.

### Community 115 - "Community 115"
Cohesion: 0.50
Nodes (3): Answer, Q: Wie wurden H-2, M-5, M-7 und B-3 aus Audit #233 umgesetzt?, Source Nodes

### Community 116 - "Community 116"
Cohesion: 0.50
Nodes (3): Answer, Q: Wie wurden die Review-Kommentare zu Begleiter-Sitzungen in PR 245 behoben?, Source Nodes

### Community 117 - "Community 117"
Cohesion: 0.21
Nodes (8): datetime, Migration, Migration, test_backup_staging_contains_exports_and_manifest(), test_daily_backup_creates_one_daily_backup_run(), test_daily_backup_does_not_run_before_configured_time(), test_daily_backup_logs_missing_active_camp(), test_daily_backup_retries_failed_archive_with_existing_run()

### Community 118 - "Community 118"
Cohesion: 0.50
Nodes (3): Answer, Q: Welche Findings aus Security-Audit Issue 233 sind nach PR 245 behoben?, Source Nodes

### Community 119 - "Community 119"
Cohesion: 0.40
Nodes (4): Answer, Outcome, Q: timer läuft im public login screen auch, Source Nodes

### Community 120 - "Community 120"
Cohesion: 0.50
Nodes (3): Answer, Q: Wie sollen die verbleibenden Findings aus Security-Audit #233 umgesetzt werden?, Source Nodes

### Community 125 - "Community 125"
Cohesion: 0.13
Nodes (27): _draw_page_framework(), _draw_payment_instructions(), _draw_sum_block(), _ensure_invoice_space(), participant_pdf_response(), _payment_instructions_height(), int, Start a continuation page when a complete invoice block would cross the footer. (+19 more)

### Community 126 - "Community 126"
Cohesion: 0.67
Nodes (3): Dienstplanung im Teilnehmer-Kiosk, Einblicke in das Tool, Lagerübersicht für Admins und Bearbeiter

### Community 127 - "Community 127"
Cohesion: 0.43
Nodes (5): charge_columns(), str, test_legacy_charge_cancellation_columns_are_migrated_and_removed(), test_legacy_charge_cleanup_is_a_noop_for_current_schema(), test_legacy_charge_cleanup_removes_a_partial_legacy_schema()

### Community 129 - "Community 129"
Cohesion: 0.67
Nodes (3): deployment_update_status_json(), JsonResponse, Return live deployment status as JSON for asynchronous UI polling.

### Community 178 - "Community 178"
Cohesion: 0.12
Nodes (18): manifest(), offline(), pwa_template_context(), Any, HttpRequest, HttpResponse, JsonResponse, str (+10 more)

### Community 180 - "Community 180"
Cohesion: 0.18
Nodes (4): `src/billing`, `src/config`, `src/templates`, `tests/e2e`

### Community 181 - "Community 181"
Cohesion: 0.40
Nodes (5): EmailDelivery, Reset one permanently failed delivery after an explicit administrator action., requeue_failed_email_delivery(), email_delivery_retry(), Requeue one failed delivery after an explicit administrator action.

### Community 182 - "Community 182"
Cohesion: 0.05
Nodes (41): Decimal, Migration, Migration, Migration, Migration, test_kiosk_allows_future_quick_booking_cancel_after_earlier_settlement_run(), test_kiosk_billed_linked_participant_can_cancel_own_quick_booking(), test_kiosk_books_drink_with_camp_drink_price_and_subsidy_flag() (+33 more)

### Community 218 - "Community 218"
Cohesion: 0.33
Nodes (5): Geänderte Dateien, Manuelle Buchungen aus Preisregeln repariert, Offene Punkte, Tests, Zusammenfassung

### Community 221 - "Community 221"
Cohesion: 0.14
Nodes (24): DrinkEntryFactory, ExpenseFactory, Meta, ParticipantFactory, PaymentFactory, export_dataset(), test_workbook_export_compares_cost_center_income_and_expenses(), test_admin_archives_and_restores_participant_without_deleting_financial_data() (+16 more)

### Community 266 - "test_actions_workflows.py"
Cohesion: 0.35
Nodes (10): test_ci_separates_quality_python_and_browser_checks(), test_ci_skips_expensive_checks_for_docs_but_always_reports_the_gate(), test_ci_uses_version_matched_playwright_container_without_runtime_install(), test_docker_publish_waits_for_successful_current_main_ci(), test_docker_validates_relevant_pull_requests_without_publishing(), test_long_running_workflows_cancel_only_stale_pull_request_runs(), test_pull_request_title_check_does_not_run_for_new_commits(), test_workflow_jobs_define_bounded_timeouts() (+2 more)

### Community 267 - "create_manual_charge"
Cohesion: 0.22
Nodes (10): BookingAuditLog, create_booking_delete_audit_log(), create_manual_charge(), Charge, Participant, PriceRule, Create a manual charge from validated price-rule input.      Args:         parti, Persist an audit entry before a booking charge is deleted.      Args:         ch (+2 more)

### Community 269 - "test_user_management.py"
Cohesion: 0.36
Nodes (9): _admin_user(), test_admin_can_change_user_role(), test_admin_can_create_admin_user(), test_admin_can_create_editor_user(), test_admin_can_reset_user_password(), test_app_admin_cannot_edit_or_reset_superuser(), test_deactivated_user_cannot_authenticate(), test_last_active_admin_cannot_be_deactivated_or_demoted() (+1 more)

### Community 335 - "Community 335"
Cohesion: 0.07
Nodes (22): BaseCommand, Command, BaseCommand, Command, Any, BaseCommand, Deliver only email outbox entries created by explicit administrator actions., Command (+14 more)

### Community 338 - "Community 338"
Cohesion: 0.29
Nodes (4): date, Return True if the camp starts in the future relative to on_date., Return True if the camp has ended in the past relative to on_date., Return the number of days remaining until the camp starts, or None.

### Community 342 - "Community 342"
Cohesion: 0.12
Nodes (30): CampAnnouncementForm, EmailConfigurationForm, InformationEmailForm, ManualEmailContentForm, Meta, str, Edit the singleton SMTP configuration without exposing its stored password., SettlementEmailForm (+22 more)

### Community 350 - "Community 350"
Cohesion: 0.11
Nodes (23): MealOrder, calculate_meal_overview(), camp_meal_dates(), _cost_center_snapshot_data(), is_meal_change_locked(), meal_change_lock_message(), meal_order_for_date(), MealCount (+15 more)

### Community 352 - "Community 352"
Cohesion: 0.06
Nodes (12): subscription_payload(), test_admin_can_create_and_update_own_push_subscription(), test_booking_link_and_linked_booking_events_notify_the_other_participant(), test_disabled_web_push_rejects_new_subscriptions(), test_endpoint_cannot_silently_move_to_another_owner(), test_expense_approval_queues_after_transaction_commit(), test_expense_events_notify_admin_and_requesting_participant(), test_linked_booking_cancellation_notifies_original_booker_with_actual_actor() (+4 more)

### Community 353 - "Community 353"
Cohesion: 0.29
Nodes (11): admin_required(), editor_required(), is_admin(), is_editor(), is_huebers(), is_meal_manager(), meal_manager_required(), require_editor() (+3 more)

### Community 453 - "bytes"
Cohesion: 0.11
Nodes (37): Command, BaseCommand, Generate a VAPID key pair suitable for environment configuration., _atomic_write_secret(), _base64url(), _decode_base64url(), ensure_webpush_key_files(), _environment_keys() (+29 more)

## Knowledge Gaps
- **416 isolated node(s):** `Funktionen in V1`, `Lagerübersicht für Admins und Bearbeiter`, `Dienstplanung im Teilnehmer-Kiosk`, `Lokale Entwicklung`, `Docker` (+411 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **131 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `datetime` connect `Community 117` to `Django Admin Integration`, `Camp Settlement Exporters`, `Community 128`, `CSV and Data Importers`, `Application Settings and Setup`, `Playwright E2E Integration Tests`, `Billing Application URLs`, `Initial Database Migrations`, `Django Core Management Script`, `Migration Package Initialization`, `Custom Template Tag Initializer`, `Community 182`, `Community 55`, `Community 54`, `Community 58`, `Community 92`, `Community 221`, `Community 350`, `Community 94`, `Community 352`, `Community 125`?**
  _High betweenness centrality (0.186) - this node is a cross-community bridge._
- **Why does `_validate_keys()` connect `bytes` to `Custom Template Tag Initializer`?**
  _High betweenness centrality (0.022) - this node is a cross-community bridge._
- **Why does `UserFactory` connect `Test Data Factories` to `Community 65`, `Community 353`, `Repository Guidelines and Rules`, `Application Settings and Setup`, `test_user_management.py`, `Django Core Management Script`, `Community 52`, `Community 125`, `Billing Application URLs`, `Community 221`, `Community 127`, `Developer Codex Server Starter`, `Billing App Commands Initializer`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **Are the 82 inferred relationships involving `Camp` (e.g. with `BookingAuditLogAdmin` and `CampAdmin`) actually correct?**
  _`Camp` has 82 INFERRED edges - model-reasoned connections that need verification._
- **Are the 62 inferred relationships involving `Decimal` (e.g. with `.total()` and `.target_shifts()`) actually correct?**
  _`Decimal` has 62 INFERRED edges - model-reasoned connections that need verification._
- **Are the 65 inferred relationships involving `Participant` (e.g. with `BookingAuditLogAdmin` and `CampAdmin`) actually correct?**
  _`Participant` has 65 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Funktionen in V1`, `Lagerübersicht für Admins und Bearbeiter`, `Dienstplanung im Teilnehmer-Kiosk` to the rest of the system?**
  _741 weakly-connected nodes found - possible documentation gaps or missing edges._