import base64
import json
import logging
import uuid
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import partial
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core import signing
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.signing import BadSignature, Signer
from django.db import IntegrityError, transaction
from django.db.models import Case, Exists, IntegerField, OuterRef, Prefetch, Q, Value, When
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from .daily_settlement_backups import update_daily_backup_settings
from .deployment_updates import UpdateAgentError, check_for_update, deployment_status, install_update
from .exporters import (
    camp_settlement_csv,
    camp_workbook_response,
    drink_entries_csv,
    participant_pdf_response,
    settlement_run_csv,
    settlement_run_workbook_response,
    settlement_snapshot_pdf_response,
)
from .forms import (
    CampFlatRateSettingsForm,
    CampForm,
    ChargeForm,
    DailySettlementBackupSettingsForm,
    ExpenseForm,
    FirstAdminSetupForm,
    KioskBookingLinkInviteForm,
    KioskFamilyMemberForm,
    KioskFamilyMemberPinForm,
    KioskLoginForm,
    KioskPinChangeForm,
    KioskSelfEnrollmentForm,
    ManualChargeForm,
    MealBookingForm,
    MealCutoffForm,
    MealPlanForm,
    MealStandardPricesForm,
    ParticipantForm,
    ParticipantImportForm,
    ParticipantPinForm,
    ParticipantRegistrationApprovalForm,
    PaymentForm,
    PriceRuleForm,
    QuickBookingForm,
    SharedExpenseApprovalForm,
    SharedExpenseRequestForm,
    ShiftForm,
    UserCreateForm,
    UserEditForm,
    UserPasswordResetForm,
)
from .importers import preview_participants, rows_from_payload, rows_to_payload, save_participants
from .kiosk_access import (
    KIOSK_FAMILY_MEMBER_SESSION_KEY,
    KIOSK_MODE_SESSION_KEY,
    KIOSK_PARTICIPANT_SESSION_KEY,
    clear_kiosk_identity_session,
)
from .kiosk_security import (
    clear_login_rate_limit,
    consume_kiosk_registration_attempt,
    is_login_locked_out,
)
from .models import (
    BookingAuditLog,
    Camp,
    Charge,
    DailySettlementBackupLog,
    DailySettlementBackupSettings,
    Expense,
    FirstAdminBootstrapLock,
    KioskActionAuditLog,
    MealOrder,
    MealPlanEntry,
    MealSignup,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    ParticipantFamilyMemberPin,
    ParticipantPin,
    PriceRule,
    Settlement,
    SettlementRun,
    Shift,
    ShiftAssignment,
)
from .notifications import (
    notify_booking_link,
    notify_expense_submitted,
    notify_kiosk_partner_action,
    notify_linked_booking,
    notify_participant_registration_submitted,
    notify_shift_exchange,
)
from .permissions import (
    ADMIN_GROUP,
    EDITOR_GROUP,
    HUEBERS_GROUP,
    admin_required,
    editor_required,
    is_editor,
    meal_manager_required,
    superuser_required,
)
from .pwa_views import pwa_template_context
from .roles import (
    ROLE_ADMIN,
    ROLE_EDITOR,
    ROLE_HUEBERS,
    active_admin_count,
    bootstrap_default_roles,
    set_user_role,
    user_role,
)
from .services import (
    admin_interface_contacts,
    calculate_camp_settlements,
    calculate_meal_overview,
    calculate_participant_settlement,
    camp_meal_dates,
    charge_audit_snapshot,
    create_booking_audit_log,
    create_booking_delete_audit_log,
    create_kiosk_action_audit_log,
    create_manual_charge,
    create_settlement_run,
    is_meal_change_locked,
    kiosk_charge_audit_snapshot,
    kiosk_meal_signup_audit_snapshot,
    meal_change_lock_message,
    meal_order_for_date,
    next_catering_order_date,
    participant_kiosk_summaries,
    participant_kiosk_summary,
    resolve_meal_price_rule,
    resolve_quick_booking_price_rule,
    restore_booking_from_audit_log,
)

logger = logging.getLogger(__name__)
signer = Signer()
User = get_user_model()
PRE_CAMP_KIOSK_ACTIONS = frozenset(
    {
        "family_member_create",
        "family_member_deactivate",
        "family_member_pin_set",
        "pin_change",
    }
)
POST_CAMP_KIOSK_ACTIONS = frozenset({"pin_change", "donate"})
GUARDIAN_ONLY_KIOSK_ACTIONS = frozenset(
    {
        "family_member_create",
        "family_member_deactivate",
        "family_member_pin_set",
    }
)
KIOSK_QUICK_BOOKING_CANCEL_WINDOW = timedelta(minutes=15)
KIOSK_QUICK_CONFIRMATION_SIGNING_SALT = "billing.kiosk-quick-confirmation.v1"
KIOSK_QUICK_CONFIRMATION_MAX_AGE_SECONDS = 10 * 60
KIOSK_MEAL_RETRACTION_SIGNING_SALT = "billing.kiosk-meal-retraction.v1"
KIOSK_MEAL_RETRACTION_MAX_AGE_SECONDS = 10 * 60
KIOSK_CHECKIN_STATE_SIGNING_SALT = "billing.kiosk-checkin-state.v1"


def _positive_int_or_none(value: Any) -> int | None:
    """Return a positive integer for an untrusted form value, otherwise ``None``."""
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        return None
    return parsed_value if parsed_value > 0 else None


def _kiosk_quick_confirmation_payload(
    *,
    participant: Participant,
    selected_rule: PriceRule,
    quantity: int,
    occurred_on: date,
    target_ids: list[str],
    resolved_bookings: list[
        tuple[
            Participant | ParticipantFamilyMember,
            Participant,
            ParticipantFamilyMember | None,
            PriceRule,
        ]
    ],
) -> dict[str, object]:
    """Return the exact JSON-safe charge set shown in a quick-booking preview."""
    return {
        "participant_id": participant.pk,
        "camp_id": participant.camp_id,
        "selected_price_rule_id": selected_rule.pk,
        "quantity": quantity,
        "occurred_on": occurred_on.isoformat(),
        "bookings": [
            {
                "target_token": target_id,
                "charge_participant_id": charge_participant.pk,
                "family_member_id": target_family_member.pk if target_family_member is not None else None,
                "effective_price_rule_id": effective_rule.pk,
                "effective_price_rule_name": effective_rule.name,
                "kind": effective_rule.kind,
                "unit_price": str(effective_rule.unit_price),
                "foerdersatz": str(effective_rule.foerdersatz),
            }
            for target_id, (_, charge_participant, target_family_member, effective_rule) in zip(
                target_ids,
                resolved_bookings,
                strict=True,
            )
        ],
    }


def _kiosk_price_rule_state(price_rule: PriceRule) -> tuple[object, ...]:
    """Return all mutable rule fields that can affect a kiosk booking."""
    return (
        price_rule.pk,
        price_rule.camp_id,
        price_rule.kind,
        price_rule.name,
        price_rule.unit_price,
        price_rule.foerdersatz,
        price_rule.meal_type,
        price_rule.meal_date,
        price_rule.applies_to_children,
        price_rule.applies_to_adults,
        price_rule.applies_to_companions,
        price_rule.is_default,
        price_rule.is_archived,
    )


def _lock_kiosk_price_rules(camp: Camp) -> dict[int, PriceRule]:
    """Lock every camp price rule so effective-rule resolution cannot race an edit."""
    return {
        price_rule.pk: price_rule
        for price_rule in PriceRule.objects.select_for_update(of=("self",)).filter(camp=camp).order_by("pk")
    }


def _revalidate_locked_meal_price_rule(
    *,
    locked_price_rules: dict[int, PriceRule],
    submitted_price_rule: PriceRule,
    camp: Camp,
    meal: str,
    meal_date: date,
    is_child: bool,
    is_companion: bool,
) -> PriceRule:
    """Return the locked meal rule only if it still matches the submitted snapshot."""
    current_price_rule = resolve_meal_price_rule(
        camp,
        meal,
        meal_date,
        is_child=is_child,
        is_companion=is_companion,
    )
    locked_price_rule = locked_price_rules.get(current_price_rule.pk) if current_price_rule is not None else None
    if locked_price_rule is None or _kiosk_price_rule_state(locked_price_rule) != _kiosk_price_rule_state(
        submitted_price_rule
    ):
        raise PermissionDenied("Die Preisregel wurde zwischenzeitlich geändert.")
    return locked_price_rule


def _sign_kiosk_quick_confirmation(payload: dict[str, object]) -> str:
    """Sign a timestamped quick-booking preview with a fresh one-time nonce."""
    signed_payload = {
        **payload,
        "nonce": str(uuid.uuid4()),
    }
    return signing.dumps(
        signed_payload,
        salt=KIOSK_QUICK_CONFIRMATION_SIGNING_SALT,
        compress=True,
    )


def _kiosk_quick_confirmation_nonce(token: str, payload: dict[str, object]) -> uuid.UUID | None:
    """Return the nonce when a non-expired token exactly matches the current charge set."""
    try:
        signed_payload = signing.loads(
            token,
            salt=KIOSK_QUICK_CONFIRMATION_SIGNING_SALT,
            max_age=KIOSK_QUICK_CONFIRMATION_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return None
    if not isinstance(signed_payload, dict):
        return None
    nonce = signed_payload.pop("nonce", None)
    if signed_payload != payload or not isinstance(nonce, str):
        return None
    try:
        return uuid.UUID(nonce)
    except ValueError:
        return None


def _kiosk_meal_retraction_payload(
    participant: Participant,
    signup: MealSignup,
) -> dict[str, object]:
    """Return the JSON-safe meal state covered by a partner retraction confirmation."""
    charge = signup.charge
    return {
        "participant_id": participant.pk,
        "camp_id": participant.camp_id,
        "signup_id": signup.pk,
        "target_participant_id": signup.participant_id,
        "family_member_id": signup.family_member_id,
        "meal_date": signup.meal_date.isoformat(),
        "meal": signup.meal,
        "variant": signup.variant,
        "status": signup.status,
        "retraction_version": signup.retraction_version,
        "charge": (
            None
            if charge is None
            else {
                "id": charge.pk,
                "owner_participant_id": charge.participant_id,
                "quantity": str(charge.quantity),
                "unit_price": str(charge.unit_price),
                "foerdersatz": str(charge.foerdersatz),
                "deleted_at": charge.deleted_at.isoformat() if charge.deleted_at is not None else None,
            }
        ),
    }


def _sign_kiosk_meal_retraction(participant: Participant, signup: MealSignup) -> str:
    """Sign the exact partner meal state shown in a retraction dialog."""
    return signing.dumps(
        _kiosk_meal_retraction_payload(participant, signup),
        salt=KIOSK_MEAL_RETRACTION_SIGNING_SALT,
        compress=True,
    )


def _matches_kiosk_meal_retraction(token: str, participant: Participant, signup: MealSignup) -> bool:
    """Return whether a non-expired token matches the current partner meal state."""
    try:
        signed_payload = signing.loads(
            token,
            salt=KIOSK_MEAL_RETRACTION_SIGNING_SALT,
            max_age=KIOSK_MEAL_RETRACTION_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return False
    return signed_payload == _kiosk_meal_retraction_payload(participant, signup)


def _kiosk_checkin_state_payload(
    participant: Participant,
    target_token: str,
    target: Participant | ParticipantFamilyMember,
) -> dict[str, object]:
    """Return the signed original attendance state rendered for one check-in row."""
    return {
        "participant_id": participant.pk,
        "camp_id": participant.camp_id,
        "target_token": target_token,
        "arrival_date": target.arrival_date.isoformat() if target.arrival_date else None,
        "departure_date": target.departure_date.isoformat() if target.departure_date else None,
    }


def _sign_kiosk_checkin_state(
    participant: Participant,
    target_token: str,
    target: Participant | ParticipantFamilyMember,
) -> str:
    """Sign a check-in row's original state for optimistic concurrency checks."""
    return signing.dumps(
        _kiosk_checkin_state_payload(participant, target_token, target),
        salt=KIOSK_CHECKIN_STATE_SIGNING_SALT,
        compress=True,
    )


def _kiosk_checkin_original_state(
    token: str,
    participant: Participant,
    target_token: str,
) -> tuple[date | None, date | None] | None:
    """Return signed original dates when token identity and values are valid."""
    try:
        payload = signing.loads(token, salt=KIOSK_CHECKIN_STATE_SIGNING_SALT)
    except signing.BadSignature:
        return None
    if not isinstance(payload, dict) or set(payload) != {
        "participant_id",
        "camp_id",
        "target_token",
        "arrival_date",
        "departure_date",
    }:
        return None
    if (
        payload["participant_id"] != participant.pk
        or payload["camp_id"] != participant.camp_id
        or payload["target_token"] != target_token
    ):
        return None

    parsed_dates: list[date | None] = []
    for field_name in ("arrival_date", "departure_date"):
        raw_value = payload[field_name]
        if raw_value is None:
            parsed_dates.append(None)
            continue
        if not isinstance(raw_value, str):
            return None
        parsed_value = parse_date(raw_value)
        if parsed_value is None:
            return None
        parsed_dates.append(parsed_value)
    return parsed_dates[0], parsed_dates[1]


def kiosk_root(_request: HttpRequest) -> HttpResponse:
    """Redirect the public root to the private-device kiosk."""
    return redirect("kiosk-home")


def _kiosk_route(kiosk_mode: str, page: str) -> str:
    """Return the named route for a kiosk page in the active device mode."""
    prefix = "central-kiosk" if kiosk_mode == "central" else "kiosk"
    return f"{prefix}-{page}"


def _pre_camp_kiosk_operation_redirect(
    request: HttpRequest, participant: Participant, kiosk_mode: str
) -> HttpResponse | None:
    """Redirect pre-camp participants away from operational kiosk pages."""
    if not participant.camp.is_pre_camp():
        return None
    messages.error(request, "Diese Funktion ist erst ab Lagerbeginn verfügbar.")
    return redirect(_kiosk_route(kiosk_mode, "home"))


def _post_camp_kiosk_operation_redirect(
    request: HttpRequest, participant: Participant, kiosk_mode: str
) -> HttpResponse | None:
    """Redirect post-camp participants away from mutating kiosk pages."""
    if not participant.camp.is_post_camp():
        return None
    messages.error(request, "Das Lager ist beendet. Änderungen sind nicht mehr möglich.")
    return redirect(_kiosk_route(kiosk_mode, "home"))


def _kiosk_operation_redirect(request: HttpRequest, participant: Participant, kiosk_mode: str) -> HttpResponse | None:
    """Redirect outside the camp's operational phase."""
    return _pre_camp_kiosk_operation_redirect(request, participant, kiosk_mode) or _post_camp_kiosk_operation_redirect(
        request, participant, kiosk_mode
    )


def _clear_kiosk_session(request: HttpRequest) -> None:
    """Remove every participant identity and setup value from a kiosk session."""
    clear_kiosk_identity_session(request)


def _activate_kiosk_mode(request: HttpRequest, kiosk_mode: str) -> None:
    """Bind the session to a route-enforced kiosk mode and isolate identities."""
    previous_mode = request.session.get(KIOSK_MODE_SESSION_KEY)
    if previous_mode and previous_mode != kiosk_mode:
        _clear_kiosk_session(request)
    request.session[KIOSK_MODE_SESSION_KEY] = kiosk_mode
    if kiosk_mode == "central":
        request.session.set_expiry(120)


def _kiosk_context(kiosk_mode: str) -> dict[str, Any]:
    """Return shared routing, session, and PWA context for kiosk templates."""
    central = kiosk_mode == "central"
    return {
        "kiosk_mode": kiosk_mode,
        "kiosk_autologout": central,
        "kiosk_urls": {
            "home": reverse(_kiosk_route(kiosk_mode, "home")),
            "login": reverse(_kiosk_route(kiosk_mode, "login")),
            "logout": reverse(_kiosk_route(kiosk_mode, "logout")),
            "partner_activity": reverse(_kiosk_route(kiosk_mode, "partner-activity")),
            "shifts": reverse(_kiosk_route(kiosk_mode, "shifts")),
            "shared_expense_request": reverse(_kiosk_route(kiosk_mode, "shared-expense-request")),
        },
        **pwa_template_context("central" if central else "kiosk"),
    }


def _notify_shift_exchange_by_id(
    assignment_id: int,
    event: str,
    actor_id: int,
    previous_participant_id: int | None = None,
) -> None:
    """Load committed shift records and enqueue an exchange notification."""
    previous_participant = (
        Participant.objects.get(pk=previous_participant_id) if previous_participant_id is not None else None
    )
    notify_shift_exchange(
        ShiftAssignment.objects.select_related("shift", "shift__camp").get(pk=assignment_id),
        event=event,
        actor=Participant.objects.get(pk=actor_id),
        previous_participant=previous_participant,
    )


def _notify_participant_registration_submitted_by_id(participant_id: int) -> None:
    """Load a committed kiosk registration before queuing administrative notifications."""
    notify_participant_registration_submitted(Participant.objects.select_related("camp").get(pk=participant_id))


def _kiosk_shift_redirect(request: HttpRequest, kiosk_mode: str):
    """Redirect to the shift page while retaining its active filters."""
    filters = {key: request.POST.get(key, "").strip() for key in ("date", "name") if request.POST.get(key, "").strip()}
    query = urlencode(filters)
    target = reverse(_kiosk_route(kiosk_mode, "shifts"))
    return redirect(f"{target}?{query}" if query else target)


def _book_open_kiosk_shifts(
    participant: Participant, shift_ids: list[int], today: date
) -> tuple[list[Shift], str | None]:
    """Book several open shifts atomically after locking their capacity rows."""
    with transaction.atomic():
        locked_shifts = list(
            Shift.objects.select_for_update().filter(pk__in=shift_ids, camp=participant.camp).order_by("pk")
        )
        if len(locked_shifts) != len(shift_ids):
            return [], "Mindestens ein ausgewählter Dienst ist nicht verfügbar. Es wurde nichts gebucht."

        assignments = list(
            ShiftAssignment.objects.filter(shift_id__in=shift_ids).values(
                "shift_id", "participant_id", "offered_for_exchange"
            )
        )
        assignments_by_shift: dict[int, list[Any]] = {shift.pk: [] for shift in locked_shifts}
        for assignment in assignments:
            assignments_by_shift[assignment["shift_id"]].append(assignment)

        for shift in locked_shifts:
            shift_assignments = assignments_by_shift[shift.pk]
            if shift.date < today:
                return [], "Ein ausgewählter Dienst liegt in der Vergangenheit. Es wurde nichts gebucht."
            if any(item["participant_id"] == participant.pk for item in shift_assignments):
                return (
                    [],
                    "Du bist für mindestens einen ausgewählten Dienst bereits eingetragen. Es wurde nichts gebucht.",
                )
            if any(item["offered_for_exchange"] for item in shift_assignments):
                return [], "Mindestens ein ausgewählter Dienst ist aktuell ein Tauschangebot. Es wurde nichts gebucht."
            if len(shift_assignments) >= shift.required_slots:
                return [], "Mindestens ein ausgewählter Dienst ist inzwischen voll. Es wurde nichts gebucht."

        ShiftAssignment.objects.bulk_create(
            [ShiftAssignment(shift=shift, participant=participant) for shift in locked_shifts]
        )
        return locked_shifts, None


@superuser_required
def deployment_update(request: HttpRequest) -> HttpResponse:
    """Show image metadata and the latest deployment-agent state."""
    status: dict[str, Any] | None = None
    agent_error = ""
    try:
        status = deployment_status()
    except UpdateAgentError as error:
        agent_error = str(error)
    current = {
        "version": settings.APP_VERSION,
        "revision": settings.APP_REVISION,
        "build_date": settings.APP_BUILD_DATE,
        "change": settings.APP_CHANGE,
    }
    backup_settings = DailySettlementBackupSettings.load()
    backup_form = DailySettlementBackupSettingsForm(instance=backup_settings)
    latest_backup_log = (
        DailySettlementBackupLog.objects.select_related("camp", "settlement_run")
        .order_by("-run_date", "-created_at")
        .first()
    )
    return render(
        request,
        "billing/deployment_update.html",
        {
            "deployment_status": status,
            "agent_error": agent_error,
            "current": current,
            "daily_backup_form": backup_form,
            "latest_backup_log": latest_backup_log,
        },
    )


@superuser_required
@require_GET
def deployment_update_status_json(request: HttpRequest) -> JsonResponse:
    """Return live deployment status as JSON for asynchronous UI polling."""
    try:
        status = deployment_status()
    except UpdateAgentError as error:
        error_message = (
            error.args[0] if error.args and isinstance(error.args[0], str) else "Der Update-Agent ist nicht verfügbar."
        )
        return JsonResponse({"active": False, "phase": "error", "error": error_message}, status=503)
    return JsonResponse(status)


@superuser_required
@require_POST
def deployment_update_check(request: HttpRequest) -> HttpResponse:
    """Pull the configured latest image and compare it with the running image."""
    try:
        result = check_for_update()
    except UpdateAgentError as error:
        messages.error(request, str(error))
    else:
        if result.get("update_available"):
            messages.success(request, "Ein neues Container-Image ist verfügbar.")
        else:
            messages.info(request, "Die Anwendung verwendet bereits das neueste Image.")
    return redirect("deployment-update")


@superuser_required
@require_POST
def deployment_update_install(request: HttpRequest) -> HttpResponse:
    """Ask the isolated agent to install the latest image asynchronously."""
    try:
        install_update()
    except UpdateAgentError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Update gestartet. Die Anwendung wird in Kürze neu gestartet.")
    return redirect("deployment-update")


@superuser_required
@require_POST
def deployment_daily_backup_settings(request: HttpRequest) -> HttpResponse:
    """Persist the daily settlement backup schedule from the Updates page."""
    backup_settings = DailySettlementBackupSettings.load()
    form = DailySettlementBackupSettingsForm(request.POST, instance=backup_settings)
    if form.is_valid():
        update_daily_backup_settings(
            enabled=form.cleaned_data["enabled"],
            run_time=form.cleaned_data["run_time"],
        )
        messages.success(request, "Tägliche Abrechnungs-Backups wurden gespeichert.")
    else:
        messages.error(request, "Die Backup-Einstellungen konnten nicht gespeichert werden.")
    return redirect("deployment-update")


class FirstLaunchLoginView(LoginView):
    def dispatch(self, request, *args, **kwargs):
        if not User.objects.exists():
            return redirect("setup")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Expose whether the optional passkey login is enabled."""
        context = super().get_context_data(**kwargs)
        context["passkey_enabled"] = settings.PASSKEY_ENABLED
        return context


def setup_first_admin(request):
    if User.objects.exists():
        return redirect("camp-list" if request.user.is_authenticated else "login")

    form = FirstAdminSetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = None
        with transaction.atomic():
            FirstAdminBootstrapLock.objects.select_for_update().get_or_create(pk=1)
            if User.objects.exists():
                form.add_error(None, "Die Ersteinrichtung wurde bereits abgeschlossen.")
            else:
                admin_group, _editor_group, _huebers_group = bootstrap_default_roles()
                user = form.save()
                user.groups.add(admin_group)
        if user is not None:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "Erster Admin-Benutzer wurde angelegt.")
            return redirect("camp-list")

    return render(request, "billing/setup.html", {"form": form})


def _is_application_admin_account(user: Any) -> bool:
    return user.is_superuser or user_role(user) == ROLE_ADMIN


def _require_superuser_for_superuser_account(request: HttpRequest, managed_user: Any) -> None:
    """Reject delegated administration of an existing superuser account."""
    if managed_user.is_superuser and not request.user.is_superuser:
        raise PermissionDenied


def _would_remove_last_active_admin(
    user: Any,
    *,
    was_active: bool,
    was_admin: bool,
    new_role: str,
    is_active: bool,
) -> bool:
    if not was_active or not was_admin:
        return False
    if is_active and new_role == ROLE_ADMIN:
        return False
    return active_admin_count(User, exclude_user=user) == 0


@admin_required
def user_list(request: HttpRequest) -> HttpResponse:
    """Render the application user management overview."""
    users = User.objects.select_related("profile").prefetch_related("groups").order_by("username")
    user_rows = []
    for managed_user in users:
        group_names = {group.name for group in managed_user.groups.all()}
        if managed_user.is_superuser or ADMIN_GROUP in group_names:
            role = ROLE_ADMIN
        elif HUEBERS_GROUP in group_names:
            role = ROLE_HUEBERS
        elif EDITOR_GROUP in group_names:
            role = ROLE_EDITOR
        else:
            role = ROLE_EDITOR
        try:
            phone = managed_user.profile.phone
        except ObjectDoesNotExist:
            phone = ""
        is_locked = is_login_locked_out(managed_user.username)
        user_rows.append({"user": managed_user, "role": role, "phone": phone, "is_locked_out": is_locked})
    return render(request, "billing/user_list.html", {"user_rows": user_rows})


@admin_required
@require_POST
def user_unlock(request: HttpRequest, user_id: int) -> HttpResponse:
    """Reset failed login attempt rate limits for an application user."""
    managed_user = get_object_or_404(User, pk=user_id)
    _require_superuser_for_superuser_account(request, managed_user)
    clear_login_rate_limit(managed_user.username, request=request)
    logger.info("Admin '%s' reset login rate-limit timeout for user '%s'.", request.user, managed_user.username)
    messages.success(request, f"Timeout für '{managed_user.username}' wurde zurückgesetzt.")
    return redirect("user-list")


@admin_required
def user_create(request: HttpRequest) -> HttpResponse:
    """Create a new application user and assign the selected billing role."""
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            set_user_role(user, form.cleaned_data["role"])
        messages.success(request, "Benutzer wurde angelegt.")
        return redirect("user-list")
    return render(request, "billing/form.html", {"form": form, "title": "Benutzer anlegen"})


@admin_required
def user_edit(request: HttpRequest, user_id: int) -> HttpResponse:
    """Edit account status and billing role for an existing user."""
    managed_user = get_object_or_404(User.objects.prefetch_related("groups"), pk=user_id)
    _require_superuser_for_superuser_account(request, managed_user)
    was_active = managed_user.is_active
    was_admin = _is_application_admin_account(managed_user)
    form = UserEditForm(request.POST or None, instance=managed_user)
    if request.method == "POST" and form.is_valid():
        if _would_remove_last_active_admin(
            managed_user,
            was_active=was_active,
            was_admin=was_admin,
            new_role=form.cleaned_data["role"],
            is_active=form.cleaned_data["is_active"],
        ):
            form.add_error(None, "Der letzte aktive Admin kann nicht deaktiviert oder herabgestuft werden.")
        else:
            with transaction.atomic():
                user = form.save()
                set_user_role(user, form.cleaned_data["role"])
            messages.success(request, "Benutzer wurde gespeichert.")
            return redirect("user-list")
    return render(request, "billing/form.html", {"form": form, "title": "Benutzer bearbeiten"})


@admin_required
def user_password_reset(request: HttpRequest, user_id: int) -> HttpResponse:
    """Set a new password for an existing application user."""
    managed_user = get_object_or_404(User, pk=user_id)
    _require_superuser_for_superuser_account(request, managed_user)
    form = UserPasswordResetForm(managed_user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        clear_login_rate_limit(managed_user.username)
        messages.success(request, "Passwort wurde neu gesetzt.")
        return redirect("user-list")
    return render(request, "billing/form.html", {"form": form, "title": "Passwort neu setzen"})


@login_required
def camp_list(request):
    camps = Camp.objects.all()
    return render(request, "billing/camp_list.html", {"camps": camps})


@admin_required
def camp_create(request):
    form = CampForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        camp = form.save()
        messages.success(request, "Lager wurde angelegt.")
        return redirect("camp-detail", camp_id=camp.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Lager anlegen"})


@admin_required
def camp_edit(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = CampForm(request.POST or None, instance=camp)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
        messages.success(request, "Lager wurde gespeichert.")
        return redirect("camp-detail", camp_id=camp.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Lager bearbeiten", "camp": camp})


@editor_required
def camp_detail(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    settlements = calculate_camp_settlements(camp)
    archived_participants = camp.participants.filter(archived_at__isnull=False).order_by("last_name", "first_name")
    settlement_runs = camp.settlement_runs.select_related("calculated_by").all()
    totals = {
        "gross": sum(result.total_gross for result in settlements),
        "subsidy": sum(result.total_subsidy for result in settlements),
        "due": sum(result.total_due for result in settlements),
        "paid": sum(result.total_paid for result in settlements),
        "advanced": sum(result.total_advanced for result in settlements),
        "balance": sum(result.balance for result in settlements),
    }
    price_rules = camp.price_rules.all()
    pending_expenses = camp.expenses.filter(status=Expense.Status.PENDING)
    pending_registrations = list(
        camp.participants.select_related("pin")
        .filter(status=Participant.Status.PENDING_APPROVAL, archived_at__isnull=True)
        .order_by("created_at", "pk")
    )
    pending_registration_rows = [
        {
            "participant": pending_participant,
            "approval_form": ParticipantRegistrationApprovalForm(
                instance=pending_participant,
                auto_id=f"approval-{pending_participant.pk}-%s",
            ),
        }
        for pending_participant in pending_registrations
    ]
    from .services import get_cost_center_evaluation

    cost_centers = get_cost_center_evaluation(camp)

    return render(
        request,
        "billing/camp_detail.html",
        {
            "camp": camp,
            "settlements": settlements,
            "totals": totals,
            "price_rules": price_rules,
            "archived_participants": archived_participants,
            "settlement_runs": settlement_runs,
            "pending_expenses": pending_expenses,
            "pending_registration_rows": pending_registration_rows,
            "cost_centers": cost_centers,
        },
    )


@editor_required
@require_POST
def approve_participant_registration(request, camp_id, participant_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    participant = get_object_or_404(
        Participant.objects.select_related("pin"),
        pk=participant_id,
        camp=camp,
        status=Participant.Status.PENDING_APPROVAL,
        archived_at__isnull=True,
    )
    pin_record = getattr(participant, "pin", None)
    if pin_record is None or pin_record.must_set_pin or not pin_record.pin_hash:
        messages.error(
            request,
            "Vor der Freigabe muss für den Teilnehmer eine PIN gesetzt sein.",
        )
        return redirect("camp-detail", camp_id=camp.pk)

    form = ParticipantRegistrationApprovalForm(request.POST, instance=participant)
    if not form.is_valid():
        messages.error(
            request,
            "Bitte prüfe und bestätige die preisrelevanten Angaben vor der Freigabe.",
        )
        return redirect("camp-detail", camp_id=camp.pk)

    with transaction.atomic():
        participant = form.save(commit=False)
        participant.status = Participant.Status.REGISTERED
        participant.save(
            update_fields=[
                "is_child",
                "is_youth_group",
                "is_companion",
                "hilfssatz",
                "berufssatz",
                "status",
                "updated_at",
            ]
        )
    messages.success(
        request,
        f"Die Registrierung von {participant.full_name} wurde erfolgreich freigegeben. "
        "Der Teilnehmer kann sich nun im Kiosk anmelden.",
    )
    return redirect("camp-detail", camp_id=camp.pk)


@editor_required
@require_POST
def reject_participant_registration(request, camp_id, participant_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    participant = get_object_or_404(
        Participant,
        pk=participant_id,
        camp=camp,
        status=Participant.Status.PENDING_APPROVAL,
        archived_at__isnull=True,
    )
    name = participant.full_name
    participant.delete()
    messages.info(request, f"Die Registrierungsanfrage von {name} wurde abgelehnt und entfernt.")
    return redirect("camp-detail", camp_id=camp.pk)


@editor_required
def participant_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = ParticipantForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            participant = form.save(commit=False)
            participant.camp = camp
            participant.save()
        messages.success(request, "Teilnehmer wurde gespeichert.")
        return redirect("participant-detail", participant_id=participant.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Teilnehmer anlegen", "camp": camp})


@editor_required
def participant_edit(request, participant_id):
    participant = get_object_or_404(Participant.objects.select_related("camp"), pk=participant_id)
    form = ParticipantForm(request.POST or None, instance=participant)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Teilnehmer wurde gespeichert.")
        return redirect("participant-detail", participant_id=participant.pk)
    return render(
        request,
        "billing/form.html",
        {"form": form, "title": "Teilnehmer bearbeiten", "camp": participant.camp},
    )


@admin_required
@require_POST
def participant_archive(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id, archived_at__isnull=True)
    participant.archived_at = timezone.now()
    participant.archived_by = request.user
    participant.save(update_fields=["archived_at", "archived_by", "updated_at"])
    messages.success(request, "Teilnehmer wurde archiviert.")
    return redirect("camp-detail", camp_id=participant.camp_id)


@admin_required
@require_POST
def participant_restore(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id, archived_at__isnull=False)
    participant.archived_at = None
    participant.archived_by = None
    participant.save(update_fields=["archived_at", "archived_by", "updated_at"])
    messages.success(request, "Teilnehmer wurde wiederhergestellt.")
    return redirect("participant-detail", participant_id=participant.pk)


@editor_required
def participant_detail(request, participant_id):
    participant = get_object_or_404(Participant.objects.select_related("camp"), pk=participant_id)
    manual_charge_form = ManualChargeForm(camp=participant.camp)

    if request.method == "POST" and request.POST.get("action") == "add_manual_charge":
        if participant.archived_at is not None:
            raise Http404
        manual_charge_form = ManualChargeForm(request.POST, camp=participant.camp)
        if manual_charge_form.is_valid():
            rule = manual_charge_form.cleaned_data["price_rule_id"]
            try:
                create_manual_charge(
                    participant=participant,
                    price_rule=rule,
                    quantity=manual_charge_form.cleaned_data["quantity"],
                    description=manual_charge_form.cleaned_data["description"],
                )
            except ValidationError as error:
                participant_error_codes = {
                    "manual_charge_participant_archived",
                    "manual_charge_participant_unavailable",
                }
                error_field = None if error.code in participant_error_codes else "price_rule_id"
                manual_charge_form.add_error(error_field, error)
            else:
                messages.success(request, f"Buchung '{rule.name}' hinzugefügt.")
                return redirect("participant-detail", participant_id=participant.pk)

    settlement = calculate_participant_settlement(participant)
    charges = participant.charges.filter(deleted_at__isnull=True).order_by("-created_at", "-id")
    audit_logs = BookingAuditLog.objects.filter(
        Q(participant=participant) | Q(charge__participant=participant)
    ).select_related("changed_by", "charge")
    settlement_snapshots = participant.settlements.filter(run__isnull=False).select_related("run", "run__camp")

    return render(
        request,
        "billing/participant_detail.html",
        {
            "participant": participant,
            "settlement": settlement,
            "charges": charges,
            "audit_logs": audit_logs,
            "settlement_snapshots": settlement_snapshots,
            "manual_charge_form": manual_charge_form,
        },
    )


@admin_required
@require_POST
def settlement_run_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    run = create_settlement_run(camp, request.user)
    messages.success(request, f"Abrechnungslauf V{run.version} wurde gespeichert.")
    return redirect("settlement-run-detail", run_id=run.pk)


@editor_required
def settlement_run_detail(request, run_id):
    run = get_object_or_404(SettlementRun.objects.select_related("camp", "calculated_by"), pk=run_id)
    snapshots = run.settlements.select_related("participant").all()
    return render(request, "billing/settlement_run_detail.html", {"run": run, "snapshots": snapshots})


@editor_required
def settlement_run_export_csv(request, run_id):
    run = get_object_or_404(SettlementRun.objects.select_related("camp"), pk=run_id)
    return settlement_run_csv(run)


@editor_required
def settlement_run_export_workbook(request, run_id):
    run = get_object_or_404(SettlementRun.objects.select_related("camp"), pk=run_id)
    return settlement_run_workbook_response(run)


@editor_required
def settlement_snapshot_export_pdf(request, settlement_id):
    snapshot = get_object_or_404(
        Settlement.objects.select_related("run", "run__camp").filter(run__isnull=False), pk=settlement_id
    )
    return settlement_snapshot_pdf_response(snapshot)


@editor_required
def charge_create(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id, archived_at__isnull=True)
    form = ChargeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            charge = form.save(commit=False)
            charge.participant = participant
            charge.save()
        messages.success(request, "Kostenposition wurde gespeichert.")
        return redirect("participant-detail", participant_id=participant.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Kostenposition erfassen"})


@admin_required
def charge_edit(request, charge_id):
    charge = get_object_or_404(
        Charge.objects.select_related("participant", "participant__camp").filter(deleted_at__isnull=True),
        pk=charge_id,
    )
    before = charge_audit_snapshot(charge)
    form = ChargeForm(request.POST or None, instance=charge)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            updated_charge = form.save()
            audit_log = create_booking_audit_log(updated_charge, before, request.user)
        if audit_log is None:
            messages.success(request, "Buchung wurde gespeichert.")
        else:
            messages.success(request, "Buchung wurde gespeichert und protokolliert.")
        return redirect("participant-detail", participant_id=charge.participant.pk)
    return render(
        request,
        "billing/form.html",
        {"form": form, "title": "Buchung bearbeiten", "camp": charge.participant.camp},
    )


@admin_required
@require_POST
def charge_delete(request: HttpRequest, charge_id: int) -> HttpResponse:
    """Mark a booking charge as deleted and keep an audit snapshot for later review."""
    charge = get_object_or_404(
        Charge.objects.select_related("participant").filter(deleted_at__isnull=True), pk=charge_id
    )
    participant_id = charge.participant_id
    before = charge_audit_snapshot(charge)
    with transaction.atomic():
        create_booking_delete_audit_log(charge, before, request.user)
        charge.deleted_at = timezone.now()
        charge.deleted_by_id = request.user.pk
        charge.save(update_fields=["deleted_at", "deleted_by"])
    messages.success(request, "Buchung wurde gelöscht und protokolliert.")
    return redirect("participant-detail", participant_id=participant_id)


@admin_required
@require_POST
def charge_batch_delete(request: HttpRequest, participant_id: int) -> HttpResponse:
    """Soft-delete multiple charges for a participant atomically."""
    participant = get_object_or_404(Participant, pk=participant_id)
    raw_ids = request.POST.getlist("selected_charges")
    selected_ids: list[int] = []
    for raw in raw_ids:
        try:
            selected_ids.append(int(raw))
        except (ValueError, TypeError):
            continue

    if not selected_ids:
        messages.warning(request, "Keine Buchungen zum Löschen ausgewählt.")
        return redirect("participant-detail", participant_id=participant.pk)

    charges = list(Charge.objects.filter(participant=participant, pk__in=selected_ids, deleted_at__isnull=True))
    if not charges:
        messages.warning(request, "Keine gültigen Buchungen zum Löschen gefunden.")
        return redirect("participant-detail", participant_id=participant.pk)

    now = timezone.now()
    with transaction.atomic():
        for charge in charges:
            before = charge_audit_snapshot(charge)
            create_booking_delete_audit_log(charge, before, request.user)
            charge.deleted_at = now
            charge.deleted_by_id = request.user.pk
            charge.save(update_fields=["deleted_at", "deleted_by"])

    messages.success(request, f"{len(charges)} Buchung(en) wurden gelöscht und protokolliert.")
    return redirect("participant-detail", participant_id=participant.pk)


@admin_required
@require_POST
def booking_audit_restore(request: HttpRequest, audit_log_id: int) -> HttpResponse:
    """Restore a deleted booking from a deletion audit entry."""
    audit_log = get_object_or_404(
        BookingAuditLog.objects.select_related("participant", "charge"),
        pk=audit_log_id,
    )
    participant_id = audit_log.participant_id
    try:
        with transaction.atomic():
            restored_charge = restore_booking_from_audit_log(audit_log, request.user)
    except ValidationError as error:
        messages.error(request, error.message)
        if participant_id is None:
            return redirect("camp-list")
        return redirect("participant-detail", participant_id=participant_id)

    messages.success(request, f"Buchung „{restored_charge.description}“ wurde wiederhergestellt.")
    return redirect("participant-detail", participant_id=restored_charge.participant_id)


@admin_required
@require_POST
def booking_audit_batch_restore(request: HttpRequest, participant_id: int) -> HttpResponse:
    """Restore multiple deleted charges from audit logs for a participant atomically."""
    participant = get_object_or_404(Participant, pk=participant_id)
    raw_ids = request.POST.getlist("selected_audit_logs")
    selected_ids: list[int] = []
    for raw in raw_ids:
        try:
            selected_ids.append(int(raw))
        except (ValueError, TypeError):
            continue

    if not selected_ids:
        messages.warning(request, "Keine Protokolleinträge zur Wiederherstellung ausgewählt.")
        return redirect("participant-detail", participant_id=participant.pk)

    audit_logs = list(
        BookingAuditLog.objects.select_related("participant", "charge").filter(
            participant=participant,
            pk__in=selected_ids,
            action=BookingAuditLog.Action.DELETED,
        )
    )

    restored_count = 0
    with transaction.atomic():
        for log in audit_logs:
            if log.charge and log.charge.deleted_at is not None:
                try:
                    restore_booking_from_audit_log(log, request.user)
                    restored_count += 1
                except ValidationError:
                    continue

    if restored_count > 0:
        messages.success(request, f"{restored_count} Buchung(en) wurden wiederhergestellt.")
    else:
        messages.warning(request, "Keine Buchungen konnten wiederhergestellt werden.")

    return redirect("participant-detail", participant_id=participant.pk)


@editor_required
def payment_create(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id, archived_at__isnull=True)
    form = PaymentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            payment = form.save(commit=False)
            payment.participant = participant
            payment.save()
        messages.success(request, "Zahlung wurde gespeichert.")
        return redirect("participant-detail", participant_id=participant.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Zahlung erfassen"})


@admin_required
def pin_reset(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id, archived_at__isnull=True)
    if request.method == "POST":
        with transaction.atomic():
            participant.pin.reset_pin(changed_by=request.user)
            participant.pin.save()
        messages.success(
            request,
            "Teilnehmer-PIN wurde gesperrt. Vor der nächsten Anmeldung muss eine neue PIN gesetzt werden.",
        )
    return redirect("participant-detail", participant_id=participant.pk)


@admin_required
@require_POST
def pin_unlock(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id, archived_at__isnull=True)
    with transaction.atomic():
        pin, _ = ParticipantPin.objects.get_or_create(participant=participant)
        pin.unlock_pin(changed_by=request.user)
        pin.save()
    logger.info(
        "Admin '%s' reset PIN timeout for participant '%s' (ID %s).",
        request.user,
        participant.full_name,
        participant.pk,
    )
    messages.success(request, "Timeout wurde zurückgesetzt.")
    return redirect("participant-detail", participant_id=participant.pk)


@admin_required
def pin_set(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id, archived_at__isnull=True)
    form = ParticipantPinForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            participant.pin.set_pin(form.cleaned_data["pin"], changed_by=request.user)
            participant.pin.save()
        messages.success(request, "Teilnehmer-PIN wurde gesetzt.")
        return redirect("participant-detail", participant_id=participant.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Teilnehmer-PIN setzen"})


@admin_required
def price_rule_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = PriceRuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            rule = form.save(commit=False)
            rule.camp = camp
            rule.save()
        messages.success(request, "Preisregel wurde gespeichert.")
        return redirect("price-rules-manage", camp_id=camp.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Preisregel anlegen"})


@admin_required
def price_rules_manage(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = CampFlatRateSettingsForm(request.POST or None, camp=camp)
    meal_form = MealStandardPricesForm(request.POST or None, camp=camp, prefix="meal")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "camp_flat" and form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, "Lagerpauschalen wurden gespeichert.")
            return redirect("price-rules-manage", camp_id=camp.pk)
        elif action == "meal_standard" and meal_form.is_valid():
            with transaction.atomic():
                meal_form.save()
            messages.success(request, "Standardpreise für Verpflegung wurden gespeichert.")
            return redirect("price-rules-manage", camp_id=camp.pk)

    grouped_rules = {
        "drinks": camp.price_rules.filter(kind=PriceRule.Kind.DRINK, is_archived=False),
        "meals": camp.price_rules.filter(kind=PriceRule.Kind.MEAL, is_default=False, is_archived=False),
        "other": camp.price_rules.filter(kind__in=[PriceRule.Kind.NIGHT, PriceRule.Kind.OTHER], is_archived=False),
    }
    return render(
        request,
        "billing/price_rules_manage.html",
        {"camp": camp, "form": form, "meal_form": meal_form, "grouped_rules": grouped_rules},
    )


@admin_required
def price_rule_edit(request, price_rule_id):
    rule = get_object_or_404(PriceRule.objects.select_related("camp"), pk=price_rule_id)
    form = PriceRuleForm(request.POST or None, instance=rule)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
        messages.success(request, "Preisregel wurde gespeichert.")
        return redirect("price-rules-manage", camp_id=rule.camp.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Preisregel bearbeiten", "camp": rule.camp})


@admin_required
@require_POST
def price_rule_delete(request, price_rule_id):
    rule = get_object_or_404(PriceRule.objects.select_related("camp"), pk=price_rule_id)
    camp_id = rule.camp_id
    if not rule.is_default:
        rule.is_archived = True
        rule.save()
        messages.success(request, f"Preisregel '{rule.name}' archiviert.")
    else:
        messages.error(request, "Standardpreise können nicht gelöscht werden.")
    return redirect("price-rules-manage", camp_id=camp_id)


@editor_required
def shift_manage(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    shifts = camp.shifts.prefetch_related("assignments__participant").order_by("date", "start_time", "name")
    return render(request, "billing/shift_manage.html", {"camp": camp, "shifts": shifts})


@editor_required
def shift_report(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    participants = list(camp.participants.all())
    # Sort by completed / target ratio
    participants.sort(
        key=lambda p: (p.completed_shifts / p.target_shifts if p.target_shifts > 0 else 0, p.completed_shifts),
        reverse=True,
    )

    total_target = sum(p.target_shifts for p in participants)
    total_completed = sum(p.completed_shifts for p in participants)
    total_percent = int(total_completed / total_target * 100) if total_target > 0 else 0

    return render(
        request,
        "billing/shift_report.html",
        {
            "camp": camp,
            "participants": participants,
            "total_target": total_target,
            "total_completed": total_completed,
            "total_percent": total_percent,
        },
    )


@editor_required
def shift_templates_manage(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    templates = camp.daily_shift_templates.all()
    return render(request, "billing/shift_templates_manage.html", {"camp": camp, "templates": templates})


@editor_required
def shift_template_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    from .forms import DailyShiftTemplateForm

    form = DailyShiftTemplateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        template = form.save(commit=False)
        template.camp = camp
        template.save()
        messages.success(request, "Dienstvorlage angelegt.")
    return redirect("shift-templates-manage", camp_id=camp.pk)


@editor_required
def shift_template_edit(request, template_id):
    from .forms import DailyShiftTemplateForm
    from .models import DailyShiftTemplate

    template = get_object_or_404(DailyShiftTemplate, pk=template_id)
    form = DailyShiftTemplateForm(request.POST or None, instance=template)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Dienstvorlage aktualisiert.")
        else:
            messages.error(request, "Fehler beim Aktualisieren der Dienstvorlage.")
    return redirect("shift-templates-manage", camp_id=template.camp_id)


@editor_required
@require_POST
def shift_templates_generate(request, camp_id):
    import datetime

    from .models import Shift

    camp = get_object_or_404(Camp, pk=camp_id)

    if not camp.starts_on or not camp.ends_on:
        messages.error(
            request,
            "Das Lager hat kein Start- oder Enddatum. Bitte setze diese zuerst in den Lagereinstellungen, "
            "bevor du Dienste generierst.",
        )
        return redirect("shift-templates-manage", camp_id=camp.pk)

    templates = camp.daily_shift_templates.all()

    generated_count = 0
    skipped_count = 0
    with transaction.atomic():
        for template in templates:
            current_date = camp.starts_on
            exceptions_by_date = {ex.date: ex for ex in template.exceptions.all()}
            while current_date <= camp.ends_on:
                exception = exceptions_by_date.get(current_date)
                if exception and exception.is_skipped:
                    skipped_count += 1
                else:
                    slots = (
                        exception.custom_required_slots
                        if exception and exception.custom_required_slots is not None
                        else template.required_slots
                    )
                    start_t = (
                        exception.custom_start_time
                        if exception and exception.custom_start_time is not None
                        else template.start_time
                    )
                    end_t = (
                        exception.custom_end_time
                        if exception and exception.custom_end_time is not None
                        else template.end_time
                    )
                    Shift.objects.update_or_create(
                        camp=camp,
                        date=current_date,
                        name=template.name,
                        start_time=start_t,
                        defaults={
                            "end_time": end_t,
                            "required_slots": slots,
                        },
                    )
                    generated_count += 1
                current_date += datetime.timedelta(days=1)

    messages.success(request, f"{generated_count} Dienste generiert, {skipped_count} übersprungen.")
    return redirect("shift-templates-manage", camp_id=camp.pk)


@editor_required
def shift_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = ShiftForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            shift = form.save(commit=False)
            shift.camp = camp
            shift.save()
        messages.success(request, "Dienst wurde angelegt.")
        return redirect("shift-manage", camp_id=camp.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Dienst anlegen", "camp": camp})


@editor_required
def shift_edit(request, shift_id):
    shift = get_object_or_404(Shift.objects.select_related("camp"), pk=shift_id)
    form = ShiftForm(request.POST or None, instance=shift)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
        messages.success(request, "Dienst wurde gespeichert.")
        return redirect("shift-manage", camp_id=shift.camp.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Dienst bearbeiten", "camp": shift.camp})


@editor_required
@require_POST
def shift_delete(request, shift_id):
    shift = get_object_or_404(Shift.objects.select_related("camp"), pk=shift_id)
    camp_id = shift.camp_id
    with transaction.atomic():
        shift.delete()
    messages.success(request, "Dienst wurde gelöscht.")
    return redirect("shift-manage", camp_id=camp_id)


@editor_required
@require_POST
def shift_bulk_delete(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    raw_shift_ids = request.POST.getlist("shift_ids")
    if not raw_shift_ids:
        messages.warning(request, "Es wurden keine Dienste zum Löschen ausgewählt.")
        return redirect("shift-manage", camp_id=camp.pk)
    parsed_shift_ids = [_positive_int_or_none(raw_shift_id) for raw_shift_id in raw_shift_ids]
    if any(shift_id is None for shift_id in parsed_shift_ids):
        messages.error(request, "Die Dienstauswahl enthält einen ungültigen Eintrag.")
        return redirect("shift-manage", camp_id=camp.pk)
    shift_ids = [shift_id for shift_id in parsed_shift_ids if shift_id is not None]

    with transaction.atomic():
        deleted_count, _ = Shift.objects.filter(camp=camp, pk__in=shift_ids).delete()

    if deleted_count > 0:
        messages.success(request, f"{deleted_count} Dienst(e) wurde(n) gelöscht.")
    else:
        messages.warning(request, "Es wurden keine passenden Dienste gefunden.")

    return redirect("shift-manage", camp_id=camp.pk)


@editor_required
def expense_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = ExpenseForm(request.POST or None, request.FILES or None)
    form.fields["participant"].queryset = Participant.objects.filter(camp=camp, archived_at__isnull=True)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            expense = form.save(commit=False)
            expense.camp = camp
            expense.save()
        messages.success(request, "Auslage wurde gespeichert.")
        return redirect("camp-detail", camp_id=camp.pk)
    return render(
        request,
        "billing/form.html",
        {"form": form, "title": "Auslage erfassen", "cancel_url": reverse("camp-detail", args=[camp.pk])},
    )


def expense_receipt_download(request: HttpRequest, expense_id: int) -> FileResponse:
    """Return an uploaded expense receipt when the requester may inspect it.

    Editors may inspect every receipt from the administrative camp overview.
    Kiosk participants may only download receipts attached to their own expense
    requests, keeping uploaded billing files out of unauthenticated public URLs.
    """
    expense = get_object_or_404(Expense.objects.select_related("participant"), pk=expense_id)
    if not expense.receipt:
        raise Http404("Kein Rechnungsbeleg vorhanden.")

    participant = _kiosk_participant(request)
    can_view_own_receipt = participant is not None and expense.participant_id == participant.pk
    if not can_view_own_receipt and not is_editor(request.user):
        raise PermissionDenied

    receipt_name = expense.receipt.name
    if not receipt_name:
        raise Http404("Kein Rechnungsbeleg vorhanden.")

    if not expense.receipt.storage.exists(receipt_name):
        logger.warning(
            "expense_receipt_file_missing",
            extra={"expense_id": expense.pk},
        )
        raise Http404("Rechnungsbeleg wurde nicht gefunden.")

    return FileResponse(
        expense.receipt.open("rb"),
        as_attachment=True,
        filename=receipt_name.rsplit("/", 1)[-1],
    )


@editor_required
def shared_expense_approve(request, expense_id):
    expense = get_object_or_404(Expense, pk=expense_id, status=Expense.Status.PENDING)
    camp = expense.camp

    form = SharedExpenseApprovalForm(request.POST or None, camp=camp)
    if request.method == "POST" and form.is_valid():
        from .services import approve_shared_expense

        allocation_method = form.cleaned_data["allocation_method"]
        participant_ids = [int(pid) for pid in form.cleaned_data.get("participant_ids", [])]
        cost_center = form.cleaned_data.get("cost_center", "")

        try:
            approve_shared_expense(
                expense,
                approved_by=request.user,
                participant_ids=participant_ids,
                allocation_method=allocation_method,
                cost_center=cost_center,
            )
            messages.success(request, "Gemeinschaftsausgabe genehmigt.")
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect("shared-expense-approve", expense_id=expense.pk)

        return redirect("camp-detail", camp_id=camp.pk)

    return render(
        request,
        "billing/shared_expense_approve.html",
        {
            "form": form,
            "title": f"Umlage genehmigen: {expense.description}",
            "camp": camp,
            "cancel_url": reverse("camp-detail", args=[camp.pk]),
        },
    )


@editor_required
@require_POST
def shared_expense_reject(request, expense_id):
    expense = get_object_or_404(Expense, pk=expense_id, status=Expense.Status.PENDING)
    rejection_reason = request.POST.get("rejection_reason", "").strip()
    from .services import reject_shared_expense

    reject_shared_expense(expense, rejected_by=request.user, rejection_reason=rejection_reason)
    messages.success(request, f"Antrag abgelehnt: {expense.description}")
    return redirect("camp-detail", camp_id=expense.camp.pk)


@editor_required
def participant_import_template_view(request, camp_id):
    from .exporters import participant_import_template_response

    return participant_import_template_response()


@editor_required
def participant_import(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = ParticipantImportForm()
    rows = None
    signed_rows = None

    if request.method == "POST" and request.POST.get("confirm"):
        try:
            payload = signer.unsign(request.POST["rows"])
            rows = rows_from_payload(json.loads(base64.b64decode(payload.encode("ascii")).decode("utf-8")))
        except (BadSignature, KeyError, ValueError, json.JSONDecodeError):
            messages.error(request, "Importdaten konnten nicht gelesen werden.")
            return redirect("participant-import", camp_id=camp.pk)
        valid_rows = [row for row in rows if row.valid]
        try:
            save_participants(camp, valid_rows)
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
            return redirect("participant-import", camp_id=camp.pk)
        messages.success(request, f"{len(valid_rows)} Teilnehmer wurden importiert.")
        return redirect("camp-detail", camp_id=camp.pk)

    if request.method == "POST":
        form = ParticipantImportForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.cleaned_data["file"]
            try:
                rows = preview_participants(upload.file, upload.name)
            except ValidationError as error:
                messages.error(request, "; ".join(error.messages))
                return redirect("participant-import", camp_id=camp.pk)
            from django.core.serializers.json import DjangoJSONEncoder

            payload = json.dumps(rows_to_payload(rows), cls=DjangoJSONEncoder, ensure_ascii=False).encode("utf-8")
            signed_rows = signer.sign(base64.b64encode(payload).decode("ascii"))

    return render(
        request,
        "billing/import_preview.html",
        {"camp": camp, "form": form, "rows": rows, "signed_rows": signed_rows},
    )


@editor_required
def export_settlements_csv(request, camp_id):
    return camp_settlement_csv(get_object_or_404(Camp, pk=camp_id))


@editor_required
def export_drinks_csv(request, camp_id):
    return drink_entries_csv(get_object_or_404(Camp, pk=camp_id))


@editor_required
def export_workbook(request, camp_id):
    return camp_workbook_response(get_object_or_404(Camp, pk=camp_id))


@editor_required
def export_participant_pdf(request, participant_id):
    return participant_pdf_response(get_object_or_404(Participant, pk=participant_id))


def _kiosk_participant_from_session(request, session_key):
    participant_id = request.session.get(session_key)
    if not participant_id:
        return None
    return (
        Participant.objects.select_related("camp")
        .filter(pk=participant_id, camp__is_active=True, archived_at__isnull=True)
        .first()
    )


def _kiosk_family_member_from_session(request, participant):
    family_member_id = request.session.get(KIOSK_FAMILY_MEMBER_SESSION_KEY)
    if not family_member_id or participant is None:
        return None
    family_member = (
        ParticipantFamilyMember.objects.select_related("guardian", "guardian__camp")
        .filter(
            pk=family_member_id,
            guardian=participant,
            guardian__camp__is_active=True,
            guardian__archived_at__isnull=True,
            role=ParticipantFamilyMember.Role.COMPANION,
            is_active=True,
        )
        .first()
    )
    if family_member is None:
        request.session.pop(KIOSK_FAMILY_MEMBER_SESSION_KEY, None)
    return family_member


def _participant_historic_settlements(participant: Participant):
    """Retrieve finalized settlements owned by this participant in the current camp."""
    return (
        Settlement.objects.filter(
            participant=participant,
            run__camp_id=participant.camp_id,
        )
        .select_related("run", "run__camp", "participant", "participant__camp")
        .order_by("-created_at")
    )


def kiosk_settlement_pdf(request, settlement_id, kiosk_mode="private"):
    """Download a finalized current-camp invoice owned by the actor or an accepted partner."""
    _activate_kiosk_mode(request, kiosk_mode)
    participant = _kiosk_participant(request)
    if participant is None:
        return redirect(_kiosk_route(kiosk_mode, "login"))

    if not participant.camp.show_kiosk_invoices:
        return HttpResponseForbidden("Rechnungen sind im Kiosk deaktiviert.")

    snapshot = get_object_or_404(
        Settlement.objects.select_related("run", "run__camp", "participant"),
        pk=settlement_id,
        run__isnull=False,
    )

    if snapshot.run.camp_id != participant.camp_id:
        return HttpResponseForbidden("Zugriff verweigert.")
    if (
        snapshot.participant_id != participant.pk
        and _accepted_booking_link_between(
            participant,
            snapshot.participant,
        )
        is None
    ):
        return HttpResponseForbidden("Zugriff verweigert.")

    return settlement_snapshot_pdf_response(snapshot)


def kiosk_current_settlement_pdf(request, kiosk_mode="private"):
    """Allow logged-in kiosk participants to download their live current settlement PDF."""
    _activate_kiosk_mode(request, kiosk_mode)
    participant = _kiosk_participant(request)
    if participant is None:
        return redirect(_kiosk_route(kiosk_mode, "login"))

    if not participant.camp.show_kiosk_invoices:
        return HttpResponseForbidden("Rechnungen sind im Kiosk deaktiviert.")

    return participant_pdf_response(participant)


def kiosk_participant_current_settlement_pdf(
    request,
    participant_id,
    kiosk_mode="private",
):
    """Download a live invoice for the actor or one accepted same-camp partner."""
    _activate_kiosk_mode(request, kiosk_mode)
    actor = _kiosk_participant(request)
    if actor is None:
        return redirect(_kiosk_route(kiosk_mode, "login"))
    if not actor.camp.show_kiosk_invoices:
        return HttpResponseForbidden("Rechnungen sind im Kiosk deaktiviert.")

    target = (
        Participant.objects.select_related("camp")
        .filter(
            pk=participant_id,
            camp=actor.camp,
            camp__is_active=True,
            archived_at__isnull=True,
        )
        .first()
    )
    if target is None:
        return HttpResponseForbidden("Zugriff verweigert.")
    if target.pk != actor.pk and _accepted_booking_link_between(actor, target) is None:
        return HttpResponseForbidden("Zugriff verweigert.")
    return participant_pdf_response(target)


def _render_kiosk_login(
    request: HttpRequest,
    kiosk_mode: str,
    *,
    form: KioskLoginForm | None = None,
    enrollment_form: KioskSelfEnrollmentForm | None = None,
    status: int = 200,
) -> HttpResponse:
    """Render one kiosk login page with optional bound forms."""
    camp = Camp.objects.filter(is_active=True).first()
    is_pre_camp = camp.is_pre_camp() if camp else False
    is_post_camp = camp.is_post_camp() if camp else False
    days_until_start = camp.days_until_start() if camp else None

    return render(
        request,
        "billing/kiosk_login.html",
        {
            "form": form or KioskLoginForm(),
            "enrollment_form": enrollment_form or KioskSelfEnrollmentForm(camp=camp, auto_id="id_enrollment_%s"),
            "camp": camp,
            "is_pre_camp": is_pre_camp,
            "is_post_camp": is_post_camp,
            "days_until_start": days_until_start,
            **_kiosk_context(kiosk_mode),
            "kiosk_autologout": False,
        },
        status=status,
    )


def kiosk_login(request, kiosk_mode="private"):
    """Authenticate a participant in a private or central kiosk session."""
    _activate_kiosk_mode(request, kiosk_mode)
    if request.session.get(KIOSK_PARTICIPANT_SESSION_KEY):
        if _kiosk_participant(request) is not None:
            return redirect(_kiosk_route(kiosk_mode, "home"))
        request.session.pop(KIOSK_PARTICIPANT_SESSION_KEY, None)
        request.session.pop(KIOSK_FAMILY_MEMBER_SESSION_KEY, None)

    form = KioskLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.session[KIOSK_PARTICIPANT_SESSION_KEY] = form.cleaned_data["participant"].pk
        family_member = form.cleaned_data.get("family_member")
        if family_member is not None:
            request.session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = family_member.pk
        else:
            request.session.pop(KIOSK_FAMILY_MEMBER_SESSION_KEY, None)
        if kiosk_mode == "private":
            request.session.set_expiry(None)
        messages.success(request, "Du bist im Kiosk angemeldet.")
        return redirect(_kiosk_route(kiosk_mode, "home"))

    return _render_kiosk_login(request, kiosk_mode, form=form)


@require_POST
def kiosk_self_register(request, kiosk_mode="private"):
    """Handle self-registration submission from Kiosk login page."""
    _activate_kiosk_mode(request, kiosk_mode)
    camp = Camp.objects.filter(is_active=True).first()
    if not camp:
        messages.error(request, "Derzeit ist kein aktives Fliegerlager konfiguriert.")
        return redirect(_kiosk_route(kiosk_mode, "login"))
    if camp.is_post_camp():
        messages.error(request, "Das Lager ist beendet. Eine Registrierung ist nicht mehr möglich.")
        return redirect(_kiosk_route(kiosk_mode, "login"))

    form = KioskSelfEnrollmentForm(request.POST, camp=camp, auto_id="id_enrollment_%s")
    access = getattr(request, "kiosk_access", None)
    if access is None:
        return HttpResponseForbidden("Gültiger Lagerzugang erforderlich.")
    if not consume_kiosk_registration_attempt(request, access):
        logger.warning("kiosk_self_registration_rate_limited", extra={"camp_id": camp.pk})
        form.add_error(None, "Zu viele Registrierungsversuche. Bitte versuche es später erneut.")
        response = _render_kiosk_login(
            request,
            kiosk_mode,
            enrollment_form=form,
            status=429,
        )
        response["Retry-After"] = str(settings.KIOSK_REGISTRATION_ATTEMPT_WINDOW)
        return response

    if form.is_valid():
        first_name = form.cleaned_data["first_name"].strip()
        last_name = form.cleaned_data["last_name"].strip()

        if Participant.objects.filter(camp=camp, first_name__iexact=first_name, last_name__iexact=last_name).exists():
            messages.error(
                request,
                f"Ein Teilnehmer mit dem Namen '{first_name} {last_name}' existiert bereits in diesem Fliegerlager.",
            )
            return redirect(_kiosk_route(kiosk_mode, "login"))

        with transaction.atomic():
            participant = form.save(commit=False)
            participant.camp = camp
            participant.status = Participant.Status.PENDING_APPROVAL
            participant.save()
            participant.pin.set_pin(form.cleaned_data["pin"])
            participant.pin.save()
            transaction.on_commit(partial(_notify_participant_registration_submitted_by_id, participant.pk))

        messages.success(
            request,
            f"Vielen Dank, {first_name}! Deine Registrierung wurde eingereicht. "
            "Die Lagerleitung muss deine Registrierung noch freigeben, bevor du dich anmelden kannst.",
        )
        return redirect(_kiosk_route(kiosk_mode, "login"))

    messages.error(request, "Fehler bei der Registrierung. Bitte überprüfe deine Eingaben.")
    return _render_kiosk_login(
        request,
        kiosk_mode,
        enrollment_form=form,
        status=400,
    )


def kiosk_logout(request, kiosk_mode="private"):
    """Clear the active kiosk identity while preserving the selected device mode."""
    _activate_kiosk_mode(request, kiosk_mode)
    _clear_kiosk_session(request)
    messages.success(request, "Du wurdest vom Kiosk abgemeldet.")
    return redirect(_kiosk_route(kiosk_mode, "login"))


def _kiosk_participant(request):
    return _kiosk_participant_from_session(request, KIOSK_PARTICIPANT_SESSION_KEY)


def _kiosk_family_member(request, participant):
    return _kiosk_family_member_from_session(request, participant)


def _accepted_booking_links(participant):
    return ParticipantBookingLink.objects.select_related("inviter", "invitee").filter(
        Q(inviter=participant, invitee__camp_id=participant.camp_id)
        | Q(invitee=participant, inviter__camp_id=participant.camp_id),
        status=ParticipantBookingLink.Status.ACCEPTED,
        inviter__camp__is_active=True,
        invitee__camp__is_active=True,
        inviter__archived_at__isnull=True,
        invitee__archived_at__isnull=True,
    )


def _accepted_booking_link_between(
    participant: Participant,
    target: Participant,
) -> ParticipantBookingLink | None:
    """Return the current same-camp partner authorization between two accounts."""
    if participant.pk == target.pk or participant.camp_id != target.camp_id:
        return None
    links = ParticipantBookingLink.objects.select_related("inviter", "invitee").filter(
        Q(inviter=participant, invitee=target) | Q(inviter=target, invitee=participant),
        status=ParticipantBookingLink.Status.ACCEPTED,
        inviter__camp=participant.camp,
        invitee__camp=participant.camp,
        inviter__camp__is_active=True,
        invitee__camp__is_active=True,
        inviter__archived_at__isnull=True,
        invitee__archived_at__isnull=True,
    )
    return links.order_by("pk").first()


def _lock_booking_authorization_dependencies(
    participants: Iterable[Participant],
    family_members: Iterable[ParticipantFamilyMember | None] = (),
    *,
    camp: Camp,
) -> tuple[Camp, dict[int, Participant], dict[int, ParticipantFamilyMember]]:
    """Lock the camp, then revalidate every submitted identity snapshot."""
    participant_snapshots_by_id: dict[int, list[Participant]] = {}
    for participant in participants:
        participant_snapshots_by_id.setdefault(participant.pk, []).append(participant)
    participant_ids = sorted(participant_snapshots_by_id)
    family_member_snapshots_by_id: dict[int, list[ParticipantFamilyMember]] = {}
    for family_member in family_members:
        if family_member is not None:
            family_member_snapshots_by_id.setdefault(family_member.pk, []).append(family_member)
    family_member_ids = sorted(family_member_snapshots_by_id)
    locked_camp = Camp.objects.select_for_update(of=("self",), no_key=True).get(pk=camp.pk)
    locked_participants = {
        participant.pk: participant
        for participant in Participant.objects.select_for_update(of=("self",), no_key=True)
        .filter(pk__in=participant_ids)
        .order_by("pk")
    }
    for participant_id, submitted_snapshots in participant_snapshots_by_id.items():
        locked_participant = locked_participants.get(participant_id)
        if locked_participant is None:
            continue
        if (
            locked_participant.camp_id != locked_camp.pk
            or locked_participant.archived_at is not None
            or any(
                locked_participant.is_child != submitted_participant.is_child
                or locked_participant.is_companion != submitted_participant.is_companion
                for submitted_participant in submitted_snapshots
            )
        ):
            locked_participants.pop(participant_id)
    locked_family_members = {}
    if family_member_ids:
        locked_family_members = {
            family_member.pk: family_member
            for family_member in ParticipantFamilyMember.objects.select_for_update(of=("self",), no_key=True)
            .select_related("guardian")
            .filter(pk__in=family_member_ids)
            .order_by("pk")
        }
    for family_member_id, submitted_family_member_snapshots in family_member_snapshots_by_id.items():
        locked_family_member = locked_family_members.get(family_member_id)
        if locked_family_member is None:
            continue
        if (
            not locked_family_member.is_active
            or any(
                locked_family_member.guardian_id != submitted_family_member.guardian_id
                or locked_family_member.role != submitted_family_member.role
                for submitted_family_member in submitted_family_member_snapshots
            )
            or locked_family_member.guardian_id not in locked_participants
        ):
            raise PermissionDenied("Das Familienmitglied ist nicht mehr verfügbar.")
    if not locked_camp.is_active:
        return locked_camp, {}, {}
    return locked_camp, locked_participants, locked_family_members


def _lock_booking_link_participant_pair(
    participant: Participant,
    target: Participant,
) -> tuple[Camp, dict[int, Participant]]:
    """Lock the camp and an unordered participant pair before changing its links."""
    expected_participant_ids = {participant.pk, target.pk}
    locked_camp, locked_participants, _locked_family_members = _lock_booking_authorization_dependencies(
        [participant, target],
        camp=participant.camp,
    )
    if len(expected_participant_ids) != 2 or set(locked_participants) != expected_participant_ids:
        return locked_camp, {}
    return locked_camp, locked_participants


def _lock_accepted_booking_links(
    participant: Participant,
    targets: Iterable[Participant],
    *,
    family_members: Iterable[ParticipantFamilyMember | None] = (),
    dependencies_locked: bool = False,
) -> dict[int, ParticipantBookingLink]:
    """Lock required FK targets, then partner authorizations, in stable order."""
    targets_by_id = {target.pk: target for target in targets if target.pk != participant.pk}
    target_ids = sorted(targets_by_id)
    family_members_by_id = {
        family_member.pk: family_member for family_member in family_members if family_member is not None
    }
    if not dependencies_locked:
        expected_participant_ids = {participant.pk, *target_ids}
        _locked_camp, locked_participants, locked_family_members = _lock_booking_authorization_dependencies(
            [participant, *targets_by_id.values()],
            family_members_by_id.values(),
            camp=participant.camp,
        )
        if set(locked_participants) != expected_participant_ids or set(locked_family_members) != set(
            family_members_by_id
        ):
            raise PermissionDenied("Die Partner-Vollmacht ist nicht mehr aktiv.")
    if not target_ids:
        return {}
    booking_links = list(
        ParticipantBookingLink.objects.select_for_update(of=("self",))
        .select_related("inviter", "invitee")
        .filter(
            Q(inviter=participant, invitee_id__in=target_ids) | Q(invitee=participant, inviter_id__in=target_ids),
            status=ParticipantBookingLink.Status.ACCEPTED,
            inviter__camp_id=participant.camp_id,
            invitee__camp_id=participant.camp_id,
            inviter__camp__is_active=True,
            invitee__camp__is_active=True,
            inviter__archived_at__isnull=True,
            invitee__archived_at__isnull=True,
        )
        .order_by("pk")
    )
    booking_links_by_target_id: dict[int, ParticipantBookingLink] = {}
    for booking_link in booking_links:
        target_id = booking_link.invitee_id if booking_link.inviter_id == participant.pk else booking_link.inviter_id
        booking_links_by_target_id.setdefault(target_id, booking_link)
    if set(booking_links_by_target_id) != set(target_ids):
        raise PermissionDenied("Die Partner-Vollmacht ist nicht mehr aktiv.")
    return booking_links_by_target_id


def _linked_booking_participants(participant):
    active_family_members = ParticipantFamilyMember.objects.filter(is_active=True).order_by(
        "last_name",
        "first_name",
    )
    return list(
        Participant.objects.filter(
            Q(
                received_booking_links__inviter=participant,
                received_booking_links__status=ParticipantBookingLink.Status.ACCEPTED,
            )
            | Q(
                sent_booking_links__invitee=participant,
                sent_booking_links__status=ParticipantBookingLink.Status.ACCEPTED,
            ),
            camp=participant.camp,
            camp__is_active=True,
            archived_at__isnull=True,
        )
        .select_related("camp")
        .distinct()
        .prefetch_related(
            Prefetch(
                "family_members",
                queryset=active_family_members,
                to_attr="active_kiosk_family_members",
            )
        )
        .order_by("last_name", "first_name", "pk")
    )


def _notify_booking_link_by_id(
    link_id: int,
    event: str,
    actor_id: int,
    actor_display_name: str,
) -> None:
    """Load committed link state before queuing its participant notification."""
    notify_booking_link(
        ParticipantBookingLink.objects.select_related("inviter", "invitee").get(pk=link_id),
        event=event,
        actor_id=actor_id,
        actor_display_name=actor_display_name,
    )


def _notify_kiosk_partner_action_by_id(audit_log_id: int) -> None:
    """Load one committed audit row before queuing its participant notification."""
    notify_kiosk_partner_action(
        KioskActionAuditLog.objects.select_related(
            "actor_participant",
            "actor_family_member",
            "target_participant",
            "target_family_member",
        ).get(pk=audit_log_id)
    )


def kiosk_partner_activity(request, kiosk_mode="private"):
    """Show current-camp partner permissions and the shared activity trail."""
    _activate_kiosk_mode(request, kiosk_mode)
    participant = _kiosk_participant(request)
    if participant is None:
        return redirect(_kiosk_route(kiosk_mode, "login"))

    actor_family_member = _kiosk_family_member(request, participant)
    booking_link_form = KioskBookingLinkInviteForm(inviter=participant, prefix="link")
    if request.method == "POST":
        if actor_family_member is not None:
            return HttpResponseForbidden("Nur Hauptteilnehmer dürfen Partner-Vollmachten verwalten.")

        action = request.POST.get("action")
        if participant.camp.is_post_camp() and action != "booking_link_revoke":
            messages.error(request, "Das Lager ist beendet. Neue Partner-Vollmachten sind nicht mehr möglich.")
            return redirect(_kiosk_route(kiosk_mode, "partner-activity"))

        if action == "booking_link_invite":
            booking_link_form = KioskBookingLinkInviteForm(request.POST, inviter=participant, prefix="link")
            if booking_link_form.is_valid():
                invitee = booking_link_form.cleaned_data["participant"]
                booking_link = None
                with transaction.atomic():
                    locked_camp, locked_pair_participants = _lock_booking_link_participant_pair(participant, invitee)
                    locked_inviter = locked_pair_participants.get(participant.pk)
                    locked_invitee = locked_pair_participants.get(invitee.pk)
                    pair_is_active = (
                        locked_camp.is_active
                        and not locked_camp.is_post_camp()
                        and locked_inviter is not None
                        and locked_invitee is not None
                        and locked_inviter.archived_at is None
                        and locked_invitee.archived_at is None
                        and locked_inviter.camp_id == participant.camp_id
                        and locked_invitee.camp_id == participant.camp_id
                    )
                    pair_filter = Q(inviter_id=participant.pk, invitee_id=invitee.pk) | Q(
                        inviter_id=invitee.pk,
                        invitee_id=participant.pk,
                    )
                    active_link_exists = (
                        pair_is_active
                        and ParticipantBookingLink.objects.filter(
                            pair_filter,
                            status__in=[
                                ParticipantBookingLink.Status.PENDING,
                                ParticipantBookingLink.Status.ACCEPTED,
                            ],
                        ).exists()
                    )
                    if not pair_is_active:
                        booking_link_form.add_error(
                            "participant",
                            "Der Teilnehmer ist nicht mehr verfügbar.",
                        )
                    elif active_link_exists:
                        booking_link_form.add_error(
                            "participant",
                            "Zwischen diesen Teilnehmern besteht bereits eine offene Verknüpfung.",
                        )
                    else:
                        booking_link = ParticipantBookingLink.objects.create(
                            inviter=locked_inviter,
                            invitee=locked_invitee,
                        )
                        create_kiosk_action_audit_log(
                            camp=locked_camp,
                            actor_participant=locked_inviter,
                            target_participant=locked_invitee,
                            booking_link=booking_link,
                            action=KioskActionAuditLog.Action.LINK_INVITED,
                            description="Partner-Vollmacht angefragt.",
                            before={},
                            after={"status": booking_link.status},
                        )
                        transaction.on_commit(
                            partial(
                                _notify_booking_link_by_id,
                                booking_link.pk,
                                "invited",
                                locked_inviter.pk,
                                locked_inviter.full_name,
                            )
                        )
                if booking_link is not None:
                    messages.success(request, "Einladung zur Partner-Vollmacht wurde gesendet.")
                    return redirect(_kiosk_route(kiosk_mode, "partner-activity"))
        elif action in {"booking_link_accept", "booking_link_decline", "booking_link_revoke"}:
            link_id = _positive_int_or_none(request.POST.get("booking_link_id"))
            new_status_by_action = {
                "booking_link_accept": ParticipantBookingLink.Status.ACCEPTED,
                "booking_link_decline": ParticipantBookingLink.Status.DECLINED,
                "booking_link_revoke": ParticipantBookingLink.Status.REVOKED,
            }
            event_by_action = {
                "booking_link_accept": "accepted",
                "booking_link_decline": "declined",
                "booking_link_revoke": "revoked",
            }
            audit_action_by_action = {
                "booking_link_accept": KioskActionAuditLog.Action.LINK_ACCEPTED,
                "booking_link_decline": KioskActionAuditLog.Action.LINK_DECLINED,
                "booking_link_revoke": KioskActionAuditLog.Action.LINK_REVOKED,
            }
            success_message_by_action = {
                "booking_link_accept": "Partner-Vollmacht wurde angenommen.",
                "booking_link_decline": "Partner-Vollmacht wurde abgelehnt.",
                "booking_link_revoke": "Partner-Vollmacht wurde widerrufen.",
            }
            booking_link = None
            candidate_link = (
                ParticipantBookingLink.objects.select_related("inviter", "invitee").filter(pk=link_id).first()
                if link_id is not None
                else None
            )
            candidate_other_participant = None
            if candidate_link is not None:
                if candidate_link.inviter_id == participant.pk:
                    candidate_other_participant = candidate_link.invitee
                elif candidate_link.invitee_id == participant.pk:
                    candidate_other_participant = candidate_link.inviter
            if candidate_other_participant is not None and candidate_other_participant.camp_id == participant.camp_id:
                with transaction.atomic():
                    locked_camp, locked_pair_participants = _lock_booking_link_participant_pair(
                        participant,
                        candidate_other_participant,
                    )
                    if locked_pair_participants:
                        locked_participant = locked_pair_participants[participant.pk]
                        locked_other_participant = locked_pair_participants[candidate_other_participant.pk]
                        pair_filter = Q(
                            inviter_id=participant.pk,
                            invitee_id=candidate_other_participant.pk,
                        ) | Q(
                            inviter_id=candidate_other_participant.pk,
                            invitee_id=participant.pk,
                        )
                        active_pair_links = list(
                            ParticipantBookingLink.objects.select_for_update(of=("self",))
                            .select_related("inviter", "invitee")
                            .filter(
                                pair_filter,
                                status__in=[
                                    ParticipantBookingLink.Status.PENDING,
                                    ParticipantBookingLink.Status.ACCEPTED,
                                ],
                            )
                            .order_by("pk")
                        )
                        selected_link = next(
                            (pair_link for pair_link in active_pair_links if pair_link.pk == link_id),
                            None,
                        )
                        if selected_link is not None:
                            selected_other_participant = locked_other_participant
                            revoke_allowed = (
                                action == "booking_link_revoke"
                                and selected_link.status == ParticipantBookingLink.Status.ACCEPTED
                            )
                            response_allowed = (
                                action != "booking_link_revoke"
                                and selected_link.invitee_id == participant.pk
                                and selected_link.status == ParticipantBookingLink.Status.PENDING
                                and selected_link.inviter.camp_id == participant.camp_id
                                and locked_camp.is_active
                                and not locked_camp.is_post_camp()
                                and locked_participant.archived_at is None
                                and locked_other_participant.archived_at is None
                            )
                            if selected_other_participant.camp_id == participant.camp_id and (
                                revoke_allowed or response_allowed
                            ):
                                booking_link = selected_link
                                before_status = booking_link.status
                                for pair_link in active_pair_links:
                                    next_status = None
                                    if action == "booking_link_revoke":
                                        next_status = ParticipantBookingLink.Status.REVOKED
                                    elif pair_link.pk == booking_link.pk:
                                        next_status = new_status_by_action[action]
                                    elif (
                                        action == "booking_link_accept"
                                        or pair_link.status == ParticipantBookingLink.Status.PENDING
                                    ):
                                        next_status = ParticipantBookingLink.Status.REVOKED
                                    if next_status is not None and pair_link.status != next_status:
                                        pair_link.status = next_status
                                        pair_link.save(update_fields=["status", "updated_at"])
                                booking_link.status = new_status_by_action[action]
                                create_kiosk_action_audit_log(
                                    camp=locked_camp,
                                    actor_participant=locked_participant,
                                    target_participant=selected_other_participant,
                                    booking_link=booking_link,
                                    action=audit_action_by_action[action],
                                    description=success_message_by_action[action],
                                    before={"status": before_status},
                                    after={"status": booking_link.status},
                                )
                                transaction.on_commit(
                                    partial(
                                        _notify_booking_link_by_id,
                                        booking_link.pk,
                                        event_by_action[action],
                                        locked_participant.pk,
                                        locked_participant.full_name,
                                    )
                                )
            if booking_link is not None:
                messages.success(request, success_message_by_action[action])
                return redirect(_kiosk_route(kiosk_mode, "partner-activity"))
            messages.error(request, "Partner-Vollmacht wurde nicht gefunden.")

    pending_invites = participant.received_booking_links.select_related("inviter").filter(
        status=ParticipantBookingLink.Status.PENDING,
        inviter__camp=participant.camp,
        inviter__camp__is_active=True,
        inviter__archived_at__isnull=True,
    )
    sent_invites = participant.sent_booking_links.select_related("invitee").filter(
        status=ParticipantBookingLink.Status.PENDING,
        invitee__camp=participant.camp,
        invitee__camp__is_active=True,
        invitee__archived_at__isnull=True,
    )
    accepted_links = list(_accepted_booking_links(participant))
    partner_invoice_accounts = []
    if participant.camp.show_kiosk_invoices:
        partners_by_id = {}
        for booking_link in accepted_links:
            partner = booking_link.invitee if booking_link.inviter_id == participant.pk else booking_link.inviter
            partners_by_id.setdefault(partner.pk, partner)
        partner_summaries = participant_kiosk_summaries(partners_by_id.values())
        settlements_by_participant = {partner_id: [] for partner_id in partners_by_id}
        for settlement in (
            Settlement.objects.filter(
                participant_id__in=partners_by_id,
                run__camp_id=participant.camp_id,
            )
            .select_related("run", "run__camp", "participant", "participant__camp")
            .order_by("-created_at")
        ):
            settlements_by_participant[settlement.participant_id].append(settlement)
        for partner in partners_by_id.values():
            settlements = [
                {
                    "snapshot": settlement,
                    "pdf_url": reverse(
                        _kiosk_route(kiosk_mode, "settlement-pdf"),
                        args=[settlement.pk],
                    ),
                }
                for settlement in settlements_by_participant[partner.pk]
            ]
            partner_invoice_accounts.append(
                {
                    "participant": partner,
                    "summary": partner_summaries[partner.pk],
                    "live_pdf_url": reverse(
                        _kiosk_route(kiosk_mode, "participant-current-settlement-pdf"),
                        args=[partner.pk],
                    ),
                    "settlements": settlements,
                }
            )
    activity_logs = (
        KioskActionAuditLog.objects.select_related(
            "actor_participant",
            "actor_family_member",
            "target_participant",
            "target_family_member",
        )
        .filter(
            Q(actor_participant=participant)
            | Q(target_participant=participant)
            | Q(booking_link__inviter=participant)
            | Q(booking_link__invitee=participant),
            camp=participant.camp,
        )
        .distinct()
        .order_by("-created_at", "-pk")[:100]
    )
    return render(
        request,
        "billing/kiosk_partner_activity.html",
        {
            "participant": participant,
            "kiosk_actor_is_family_member": actor_family_member is not None,
            "booking_link_form": booking_link_form,
            "pending_invites": pending_invites,
            "sent_invites": sent_invites,
            "accepted_links": accepted_links,
            "partner_invoice_accounts": partner_invoice_accounts,
            "activity_logs": activity_logs,
            "is_pre_camp": participant.camp.is_pre_camp(),
            "is_post_camp": participant.camp.is_post_camp(),
            **_kiosk_context(kiosk_mode),
        },
    )


def _kiosk_checkin_participants(
    participant,
    *,
    family_members=None,
    linked_participants=None,
):
    if family_members is None:
        family_members = participant.family_members.filter(is_active=True).order_by("last_name", "first_name")
    if linked_participants is None:
        linked_participants = _linked_booking_participants(participant)
    targets = [
        {
            "token": f"participant-{participant.pk}",
            "object": participant,
            "name": participant.full_name,
            "role": "Ich",
            "camp": participant.camp,
        }
    ]
    for member in family_members:
        targets.append(
            {
                "token": f"family-{member.pk}",
                "object": member,
                "name": member.full_name,
                "role": member.get_role_display(),
                "camp": participant.camp,
            }
        )
    for linked_participant in linked_participants:
        targets.append(
            {
                "token": f"participant-{linked_participant.pk}",
                "object": linked_participant,
                "name": linked_participant.full_name,
                "role": "Partnerkonto",
                "camp": linked_participant.camp,
            }
        )
        for member in linked_participant.active_kiosk_family_members:
            targets.append(
                {
                    "token": f"family-{member.pk}",
                    "object": member,
                    "name": member.full_name,
                    "role": f"Partnerkonto · {member.get_role_display()}",
                    "camp": linked_participant.camp,
                }
            )
    for target in targets:
        target["state_token"] = _sign_kiosk_checkin_state(
            participant,
            target["token"],
            target["object"],
        )
    return targets


def _parse_kiosk_checkin_date(value, field_label, participant_name, errors):
    stripped_value = (value or "").strip()
    if not stripped_value:
        return None
    parsed = parse_date(stripped_value)
    if parsed is None:
        import re
        from datetime import datetime

        match = re.match(r"^(\d{2})[\. ](\d{2})[\. ](\d{4})$", stripped_value)
        if match:
            try:
                parsed = datetime(int(match.group(3)), int(match.group(2)), int(match.group(1))).date()
            except ValueError:
                # Das Datum ist ungültig (z.B. 31.02.), parsed bleibt None und der Error wird unten gefangen
                pass
    if parsed is None:
        errors.append(f"{field_label} für {participant_name} ist kein gültiges Datum.")
    return parsed


def _validate_kiosk_checkin_dates(target, camp, arrival_date, departure_date, errors):
    if arrival_date and departure_date and departure_date <= arrival_date:
        errors.append(f"Die Abreise für {target.full_name} muss nach der Anreise liegen.")
    if camp.starts_on:
        earliest = camp.starts_on - timedelta(days=4)
        starts_formatted = camp.starts_on.strftime("%d.%m.%Y")
        if arrival_date and arrival_date < earliest:
            errors.append(
                f"Die Anreise für {target.full_name} liegt mehr als 4 Tage vor Lagerbeginn ({starts_formatted})."
            )
        if departure_date and departure_date < earliest:
            errors.append(
                f"Die Abreise für {target.full_name} liegt mehr als 4 Tage vor Lagerbeginn ({starts_formatted})."
            )
    if camp.ends_on:
        latest = camp.ends_on + timedelta(days=4)
        ends_formatted = camp.ends_on.strftime("%d.%m.%Y")
        if arrival_date and arrival_date > latest:
            errors.append(
                f"Die Anreise für {target.full_name} liegt mehr als 4 Tage nach Lagerende ({ends_formatted})."
            )
        if departure_date and departure_date > latest:
            errors.append(
                f"Die Abreise für {target.full_name} liegt mehr als 4 Tage nach Lagerende ({ends_formatted})."
            )


def _update_kiosk_checkin_dates(request, participant, checkin_participants):
    targets_by_token = {target["token"]: target for target in checkin_participants}
    submitted_tokens = list(dict.fromkeys(request.POST.getlist("checkin_target")))
    updates = []
    errors = []

    for token in submitted_tokens:
        target = targets_by_token.get(token)
        if target is None:
            errors.append("Ein Teilnehmer darf über diesen Kiosk nicht bearbeitet werden.")
            continue
        target_object = target["object"]
        original_state = _kiosk_checkin_original_state(
            request.POST.get(f"checkin_state_{token}", ""),
            participant,
            token,
        )
        if original_state is None:
            errors.append("Die Check-in-Daten konnten nicht bestätigt werden. Bitte lade die Seite neu.")
            continue
        arrival_date = _parse_kiosk_checkin_date(
            request.POST.get(f"arrival_date_{token}"),
            "Anreise",
            target["name"],
            errors,
        )
        departure_date = _parse_kiosk_checkin_date(
            request.POST.get(f"departure_date_{token}"),
            "Abreise",
            target["name"],
            errors,
        )
        _validate_kiosk_checkin_dates(target_object, target["camp"], arrival_date, departure_date, errors)
        if (arrival_date, departure_date) != original_state:
            updates.append(
                {
                    "target": target_object,
                    "arrival_date": arrival_date,
                    "departure_date": departure_date,
                    "original_state": original_state,
                }
            )

    if errors:
        for error in errors:
            messages.error(request, error)
        return False
    if not updates:
        return True

    actor_family_member = _kiosk_family_member(request, participant)
    with transaction.atomic():
        dependency_participants = [participant]
        dependency_family_members = [actor_family_member]
        for update in updates:
            submitted_target = update["target"]
            if isinstance(submitted_target, Participant):
                dependency_participants.append(submitted_target)
            else:
                dependency_participants.append(submitted_target.guardian)
                dependency_family_members.append(submitted_target)
        expected_participant_ids = {target.pk for target in dependency_participants}
        expected_family_member_ids = {target.pk for target in dependency_family_members if target is not None}
        locked_camp, locked_participants, locked_family_members = _lock_booking_authorization_dependencies(
            dependency_participants,
            dependency_family_members,
            camp=participant.camp,
        )
        if (
            set(locked_participants) != expected_participant_ids
            or set(locked_family_members) != expected_family_member_ids
        ):
            raise PermissionDenied("Der Check-in-Eintrag ist nicht mehr verfügbar.")

        partner_participants = {}
        for update in updates:
            submitted_target = update["target"]
            if isinstance(submitted_target, Participant):
                target = locked_participants.get(submitted_target.pk)
            else:
                target = locked_family_members.get(submitted_target.pk)
            if target is None:
                raise PermissionDenied("Der Check-in-Eintrag ist nicht mehr verfügbar.")
            update["locked_target"] = target
            current_state = (target.arrival_date, target.departure_date)
            if current_state != update["original_state"]:
                messages.error(
                    request,
                    "Die Check-in-Daten wurden zwischenzeitlich geändert. Bitte lade die Seite neu.",
                )
                return False
            target_participant = target if isinstance(target, Participant) else target.guardian
            if target_participant.pk != participant.pk:
                partner_participants[target_participant.pk] = target_participant

        booking_links = _lock_accepted_booking_links(
            participant,
            partner_participants.values(),
            family_members=locked_family_members.values(),
            dependencies_locked=True,
        )

        for update in updates:
            target = update["locked_target"]
            arrival_date = update["arrival_date"]
            departure_date = update["departure_date"]
            target_participant = target if isinstance(target, Participant) else target.guardian
            target_family_member = target if isinstance(target, ParticipantFamilyMember) else None
            booking_link = booking_links.get(target_participant.pk)
            before = {
                "arrival_date": target.arrival_date.isoformat() if target.arrival_date else None,
                "departure_date": target.departure_date.isoformat() if target.departure_date else None,
            }
            target.arrival_date = arrival_date
            target.departure_date = departure_date
            update_fields = ["arrival_date", "departure_date", "updated_at"]
            if isinstance(target, Participant):
                before["booked_nights"] = target.booked_nights
                target.booked_nights = (
                    max((departure_date - arrival_date).days, 0) if arrival_date and departure_date else 0
                )
                update_fields.append("booked_nights")
            target.save(update_fields=update_fields)
            after = {
                "arrival_date": target.arrival_date.isoformat() if target.arrival_date else None,
                "departure_date": target.departure_date.isoformat() if target.departure_date else None,
            }
            if isinstance(target, Participant):
                after["booked_nights"] = target.booked_nights
            if booking_link is not None and before != after:
                audit_log = create_kiosk_action_audit_log(
                    camp=locked_camp,
                    actor_participant=participant,
                    actor_family_member=actor_family_member,
                    target_participant=target_participant,
                    target_family_member=target_family_member,
                    booking_link=booking_link,
                    action=KioskActionAuditLog.Action.CHECKIN_UPDATED,
                    description="Anwesenheit geändert.",
                    before=before,
                    after=after,
                )
                transaction.on_commit(partial(_notify_kiosk_partner_action_by_id, audit_log.pk))
    messages.success(request, "Check-in-Daten wurden gespeichert.")
    return True


def _variant_choices_for_booking_target(is_child):
    if is_child:
        return [
            (MealSignup.Variant.NORMAL_CHILD, "Mit Fleisch (Kind)"),
            (MealSignup.Variant.VEGAN_CHILD, "Vegan/Vegetarisch (Kind)"),
        ]
    return [
        (MealSignup.Variant.NORMAL, "Mit Fleisch"),
        (MealSignup.Variant.VEGAN, "Vegan/Vegetarisch"),
    ]


def _kiosk_meal_targets(
    participant,
    *,
    family_members=None,
    linked_participants=None,
):
    if family_members is None:
        family_members = participant.family_members.filter(is_active=True).order_by("last_name", "first_name")
    if linked_participants is None:
        linked_participants = _linked_booking_participants(participant)
    targets = [
        {
            "token": f"participant-{participant.pk}",
            "kind": "participant",
            "object": participant,
            "name": participant.full_name,
            "role": "Ich",
            "is_child": participant.is_child,
            "is_companion": participant.is_companion,
            "variant_choices": _variant_choices_for_booking_target(participant.is_child),
        }
    ]
    for member in family_members:
        targets.append(
            {
                "token": f"family-{member.pk}",
                "kind": "family",
                "object": member,
                "name": member.full_name,
                "role": member.get_role_display(),
                "is_child": member.is_child,
                "is_companion": member.role == member.Role.COMPANION,
                "variant_choices": _variant_choices_for_booking_target(member.is_child),
            }
        )
    for linked_participant in linked_participants:
        targets.append(
            {
                "token": f"participant-{linked_participant.pk}",
                "kind": "participant",
                "object": linked_participant,
                "name": linked_participant.full_name,
                "role": "Verknüpft",
                "is_child": linked_participant.is_child,
                "is_companion": linked_participant.is_companion,
                "variant_choices": _variant_choices_for_booking_target(linked_participant.is_child),
            }
        )
        for member in linked_participant.active_kiosk_family_members:
            targets.append(
                {
                    "token": f"family-{member.pk}",
                    "kind": "family",
                    "object": member,
                    "name": member.full_name,
                    "role": f"Partnerkonto · {member.get_role_display()}",
                    "is_child": member.is_child,
                    "is_companion": member.role == member.Role.COMPANION,
                    "variant_choices": _variant_choices_for_booking_target(member.is_child),
                }
            )
    return targets


def _target_lookup(meal_targets):
    return {target["token"]: target for target in meal_targets}


def _target_token_for_signup(signup):
    if signup.family_member_id is not None:
        return f"family-{signup.family_member_id}"
    return f"participant-{signup.participant_id}"


def _meal_signup_key(
    target: dict[str, Any],
    meal_date: date,
    meal: str,
) -> tuple[int, int | None, date, str]:
    """Return the unique database identity of a target's meal signup."""
    target_object = target["object"]
    participant = target_object if target["kind"] == "participant" else target_object.guardian
    family_member_id = target_object.pk if target["kind"] == "family" else None
    return participant.pk, family_member_id, meal_date, meal


def _lock_meal_signups_for_bookings(
    bookings: list[tuple[dict[str, Any], date, str, PriceRule]],
    meal: str,
) -> tuple[
    dict[tuple[int, int | None, date, str], MealSignup],
    set[tuple[int, int | None, date, str]],
]:
    """Ensure and lock every batch signup in stable order before authorization rows."""
    bookings_by_key = {
        _meal_signup_key(target, meal_date, meal): (variant, price_rule)
        for target, meal_date, variant, price_rule in bookings
    }
    if not bookings_by_key:
        return {}, set()

    created_keys = set()
    signup_ids = []
    for signup_key in sorted(
        bookings_by_key,
        key=lambda key: (key[0], key[1] or 0, key[2], key[3]),
    ):
        participant_id, family_member_id, meal_date, meal_name = signup_key
        variant, price_rule = bookings_by_key[signup_key]
        signup, created = MealSignup.objects.get_or_create(
            participant_id=participant_id,
            family_member_id=family_member_id,
            meal_date=meal_date,
            meal=meal_name,
            defaults={
                "variant": variant,
                "status": MealSignup.Status.ACTIVE,
                "foerdersatz": price_rule.foerdersatz,
                "retracted_at": None,
            },
        )
        signup_ids.append(signup.pk)
        if created:
            created_keys.add(signup_key)

    locked_signups = list(
        MealSignup.objects.select_for_update(of=("self",))
        .select_related("charge")
        .filter(pk__in=signup_ids)
        .order_by("pk")
    )
    if len(locked_signups) != len(signup_ids):
        raise MealSignup.DoesNotExist("Eine Essensanmeldung wurde während der Buchung entfernt.")
    signups_by_key = {
        (
            signup.participant_id,
            signup.family_member_id,
            signup.meal_date,
            signup.meal,
        ): signup
        for signup in locked_signups
    }
    return signups_by_key, created_keys


def _notify_linked_booking_by_id(
    charge_id: int,
    actor_id: int,
    *,
    actor_display_name: str,
    cancelled: bool,
) -> None:
    charge = Charge.objects.select_related("participant", "kiosk_booked_by").get(pk=charge_id)
    notify_linked_booking(
        charge,
        actor_id=actor_id,
        actor_display_name=actor_display_name,
        cancelled=cancelled,
    )


def _book_meal_for_target(
    target,
    meal_date,
    meal,
    variant,
    price_rule,
    booked_by,
    actor_family_member=None,
    *,
    prelocked_signup: MealSignup | None = None,
    signup_lock_acquired: bool = False,
    signup_was_created: bool = False,
    prelocked_booking_link: ParticipantBookingLink | None = None,
    booking_link_lock_acquired: bool = False,
    dependencies_lock_acquired: bool = False,
    price_rule_lock_acquired: bool = False,
):
    """Book one meal after acquiring dependencies in the global lock order."""
    meal_display = dict(MealSignup.Meal.choices).get(meal, meal)
    target_object = target["object"]
    participant = target_object if target["kind"] == "participant" else target_object.guardian
    family_member = target_object if target["kind"] == "family" else None
    if (signup_lock_acquired or booking_link_lock_acquired) and (
        not dependencies_lock_acquired or not price_rule_lock_acquired
    ):
        raise ValueError(
            "Vorbereitete MealSignup- oder Vollmachts-Locks benötigen gesperrte Identitäten und Preisregeln."
        )
    if dependencies_lock_acquired and not price_rule_lock_acquired:
        raise ValueError("Gesperrte Identitäten benötigen eine bereits gesperrte Preisregel.")
    if not dependencies_lock_acquired:
        expected_participant_ids = {booked_by.pk, participant.pk}
        expected_family_member_ids = {
            member.pk for member in (actor_family_member, family_member) if member is not None
        }
        _locked_camp, locked_participants, locked_family_members = _lock_booking_authorization_dependencies(
            [booked_by, participant],
            [actor_family_member, family_member],
            camp=booked_by.camp,
        )
        if (
            set(locked_participants) != expected_participant_ids
            or set(locked_family_members) != expected_family_member_ids
        ):
            raise PermissionDenied("Das Buchungsziel ist nicht mehr verfügbar.")
        booked_by = locked_participants[booked_by.pk]
        participant = locked_participants[participant.pk]
        actor_family_member = locked_family_members[actor_family_member.pk] if actor_family_member is not None else None
        family_member = locked_family_members[family_member.pk] if family_member is not None else None
        dependencies_lock_acquired = True
        locked_price_rules = _lock_kiosk_price_rules(_locked_camp)
        price_rule = _revalidate_locked_meal_price_rule(
            locked_price_rules=locked_price_rules,
            submitted_price_rule=price_rule,
            camp=_locked_camp,
            meal=meal,
            meal_date=meal_date,
            is_child=family_member.is_child if family_member is not None else participant.is_child,
            is_companion=(
                family_member.role == ParticipantFamilyMember.Role.COMPANION
                if family_member is not None
                else participant.is_companion
            ),
        )
        price_rule_lock_acquired = True
    existing_signup: MealSignup | None
    if signup_lock_acquired:
        if prelocked_signup is None:
            raise MealSignup.DoesNotExist("Die vorbereitete Essensanmeldung fehlt.")
        existing_signup = prelocked_signup
    else:
        existing_signup = (
            MealSignup.objects.select_for_update(of=("self",))
            .select_related("charge")
            .filter(
                participant=participant,
                family_member=family_member,
                meal_date=meal_date,
                meal=meal,
            )
            .first()
        )
    booking_link = None
    if participant.pk != booked_by.pk:
        if booking_link_lock_acquired:
            booking_link = prelocked_booking_link
        else:
            booking_link = _lock_accepted_booking_links(
                booked_by,
                [participant],
                family_members=[actor_family_member, family_member],
                dependencies_locked=dependencies_lock_acquired,
            ).get(participant.pk)
        if booking_link is None:
            raise PermissionDenied("Die Partner-Vollmacht ist nicht mehr aktiv.")
    before = (
        kiosk_meal_signup_audit_snapshot(existing_signup)
        if existing_signup is not None and not signup_was_created
        else {}
    )
    signup_defaults = {
        "variant": variant,
        "status": MealSignup.Status.ACTIVE,
        "foerdersatz": price_rule.foerdersatz,
        "retracted_at": None,
    }
    charge_description = f"{price_rule.name} {meal_display}"
    if family_member is not None:
        charge_description = f"{charge_description} für {family_member.full_name}"
    if existing_signup is None:
        signup = MealSignup.objects.create(
            participant=participant,
            family_member=family_member,
            meal_date=meal_date,
            meal=meal,
            **signup_defaults,
        )
    else:
        signup = existing_signup
        for field_name, value in signup_defaults.items():
            setattr(signup, field_name, value)
        signup.save(
            update_fields=[
                "variant",
                "status",
                "foerdersatz",
                "retracted_at",
                "updated_at",
            ]
        )
    charge = signup.charge
    if charge is None:
        charge = Charge(participant=participant, kind=Charge.Kind.FOOD)
    charge.participant = participant
    charge.kind = Charge.Kind.FOOD
    charge.occurred_on = meal_date
    charge.description = charge_description
    charge.quantity = 1
    charge.unit_price = price_rule.unit_price
    charge.foerdersatz = price_rule.foerdersatz
    charge.kiosk_booked_by = booked_by
    charge.deleted_at = None
    charge.deleted_by = None
    charge.save()
    if signup.charge_id != charge.pk:
        signup.charge = charge
        signup.save(update_fields=["charge", "updated_at"])
    if booking_link is not None:
        signup.charge = charge
        create_kiosk_action_audit_log(
            camp=booked_by.camp,
            actor_participant=booked_by,
            actor_family_member=actor_family_member,
            target_participant=participant,
            target_family_member=family_member,
            booking_link=booking_link,
            charge=charge,
            action=KioskActionAuditLog.Action.MEAL_BOOKED,
            description=f"{charge.booking_reference}: Essensanmeldung gespeichert.",
            before=before,
            after=kiosk_meal_signup_audit_snapshot(signup),
        )
    transaction.on_commit(
        partial(
            _notify_linked_booking_by_id,
            charge.pk,
            booked_by.pk,
            actor_display_name=(
                actor_family_member.full_name if actor_family_member is not None else booked_by.full_name
            ),
            cancelled=False,
        )
    )


def _retract_meal_signup(
    signup: MealSignup,
    actor: Participant,
    actor_family_member: ParticipantFamilyMember | None = None,
    *,
    confirmation_token: str = "",
) -> bool:
    """Retract an active signup only if its locked state still matches the confirmation."""
    submitted_participant = signup.participant
    submitted_family_member = signup.family_member
    expected_participant_ids = {actor.pk, submitted_participant.pk}
    expected_family_member_ids = {
        member.pk for member in (actor_family_member, submitted_family_member) if member is not None
    }
    locked_camp, locked_participants, locked_family_members = _lock_booking_authorization_dependencies(
        [actor, submitted_participant],
        [actor_family_member, submitted_family_member],
        camp=actor.camp,
    )
    if set(locked_participants) != expected_participant_ids or set(locked_family_members) != expected_family_member_ids:
        return False
    actor = locked_participants[actor.pk]
    affected_participant = locked_participants[submitted_participant.pk]
    actor_family_member = locked_family_members[actor_family_member.pk] if actor_family_member is not None else None
    affected_family_member = (
        locked_family_members[submitted_family_member.pk] if submitted_family_member is not None else None
    )
    locked_signup = (
        MealSignup.objects.select_for_update(of=("self",))
        .select_related("participant", "family_member")
        .filter(pk=signup.pk, status=MealSignup.Status.ACTIVE)
        .first()
    )
    if (
        locked_signup is None
        or locked_signup.participant_id != affected_participant.pk
        or locked_signup.family_member_id != (affected_family_member.pk if affected_family_member is not None else None)
    ):
        return False
    locked_charge = None
    if locked_signup.charge_id is not None:
        locked_charge = Charge.objects.select_for_update(of=("self",)).filter(pk=locked_signup.charge_id).first()
        if locked_charge is None or locked_charge.participant_id != affected_participant.pk:
            return False
    locked_signup.charge = locked_charge
    booking_link = None
    if affected_participant.pk != actor.pk:
        if not _matches_kiosk_meal_retraction(confirmation_token, actor, locked_signup):
            return False
        booking_link = _lock_accepted_booking_links(
            actor,
            [affected_participant],
            family_members=[actor_family_member, affected_family_member],
            dependencies_locked=True,
        ).get(affected_participant.pk)
        if booking_link is None:
            raise PermissionDenied("Die Partner-Vollmacht ist nicht mehr aktiv.")
    elif locked_charge is not None and locked_charge.kiosk_booked_by_id != actor.pk:
        creation_audit = (
            KioskActionAuditLog.objects.select_related("booking_link")
            .filter(
                charge=locked_charge,
                action=KioskActionAuditLog.Action.MEAL_BOOKED,
            )
            .order_by("created_at", "pk")
            .first()
        )
        booking_link = creation_audit.booking_link if creation_audit is not None else None
    before = kiosk_meal_signup_audit_snapshot(locked_signup)
    locked_signup.status = MealSignup.Status.RETRACTED
    locked_signup.retraction_version += 1
    locked_signup.retracted_at = timezone.now()
    locked_signup.save(update_fields=["status", "retraction_version", "retracted_at", "updated_at"])
    charge = locked_charge
    if charge is not None:
        charge.deleted_at = timezone.now()
        charge.deleted_by = None
        charge.save(update_fields=["deleted_at", "deleted_by"])
    audit_log = None
    partner_action = affected_participant.pk != actor.pk
    linked_booking_action = charge is not None and charge.kiosk_booked_by_id != affected_participant.pk
    if partner_action or linked_booking_action:
        description = "Essensanmeldung zurückgenommen."
        if charge is not None:
            description = f"{charge.booking_reference}: {description}"
        audit_log = create_kiosk_action_audit_log(
            camp=locked_camp,
            actor_participant=actor,
            actor_family_member=actor_family_member,
            target_participant=affected_participant,
            target_family_member=affected_family_member,
            booking_link=booking_link,
            charge=charge,
            action=KioskActionAuditLog.Action.MEAL_RETRACTED,
            description=description,
            before=before,
            after=kiosk_meal_signup_audit_snapshot(locked_signup),
        )
    if audit_log is not None and partner_action:
        transaction.on_commit(partial(_notify_kiosk_partner_action_by_id, audit_log.pk))
    elif charge is not None:
        transaction.on_commit(
            partial(
                _notify_linked_booking_by_id,
                charge.pk,
                actor.pk,
                actor_display_name=(
                    actor_family_member.full_name if actor_family_member is not None else actor.full_name
                ),
                cancelled=True,
            )
        )
    return True


def _is_kiosk_quick_charge_cancelable(
    charge: Charge,
    participant: Participant,
    now=None,
    *,
    authorized_participant_ids: set[int] | None = None,
) -> bool:
    """Return whether a kiosk participant may cancel a quick charge."""
    current_time = now or timezone.now()
    has_meal_signup = getattr(charge, "has_meal_signup", None)
    if has_meal_signup is None:
        has_meal_signup = charge.meal_signups.exists()
    account_authorized = charge.participant_id == participant.pk
    if not account_authorized and authorized_participant_ids is not None:
        account_authorized = charge.participant_id in authorized_participant_ids
    elif not account_authorized:
        account_authorized = _accepted_booking_link_between(participant, charge.participant) is not None
    return (
        charge.deleted_at is None
        and not has_meal_signup
        and charge.kiosk_booked_by_id is not None
        and charge.kind in {Charge.Kind.DRINK, Charge.Kind.FOOD}
        and charge.created_at >= current_time - KIOSK_QUICK_BOOKING_CANCEL_WINDOW
        and account_authorized
        and not _is_charge_covered_by_settlement_run(charge)
    )


def _is_charge_covered_by_settlement_run(charge: Charge) -> bool:
    """Return whether a settlement run freezes this charge for kiosk cancellation."""
    settlement_runs = SettlementRun.objects.filter(
        camp_id=charge.participant.camp_id,
        created_at__gte=charge.created_at,
    ).order_by("created_at")
    for run in settlement_runs:
        if charge.occurred_on is None or charge.occurred_on <= timezone.localdate(run.created_at):
            return True
    return False


def _meal_price_rule_for_targets(camp, meal, meal_date, participant, meal_targets):
    participant_rule = resolve_meal_price_rule(
        camp,
        meal,
        meal_date,
        is_child=participant.is_child,
        is_companion=participant.is_companion,
    )
    if participant_rule is not None:
        return participant_rule
    for target in meal_targets:
        price_rule = resolve_meal_price_rule(
            camp,
            meal,
            meal_date,
            is_child=target["is_child"],
            is_companion=target["is_companion"],
        )
        if price_rule is not None:
            return price_rule
    return None


def _kiosk_meal_calendar(camp, participant, meal_signups, meal_targets, meal=MealSignup.Meal.DINNER):
    signups_by_date_meal = {}
    included_dates = {signup.meal_date for signup in meal_signups}
    for signup in meal_signups:
        signups_by_date_meal.setdefault((signup.meal_date, signup.meal), []).append(signup)

    meal_dates = camp_meal_dates(camp, included_dates)
    menu_descriptions = {
        entry.meal_date: entry.description
        for entry in MealPlanEntry.objects.filter(camp=camp, meal=meal, meal_date__in=meal_dates)
    }
    sent_order_dates = set(
        MealOrder.objects.filter(camp=camp, meal_date__in=meal_dates).values_list("meal_date", flat=True)
    )
    meal_labels = dict(MealSignup.Meal.choices)
    days = []
    for meal_date in meal_dates:
        meals = []
        scoped = signups_by_date_meal.get((meal_date, meal), [])
        active_signups = [signup for signup in scoped if signup.status == MealSignup.Status.ACTIVE]
        retracted_signups = [signup for signup in scoped if signup.status == MealSignup.Status.RETRACTED]
        locked = is_meal_change_locked(camp, meal_date, sent_order_dates=sent_order_dates)
        lock_message = meal_change_lock_message(camp, meal_date, sent_order_dates=sent_order_dates) if locked else ""
        if active_signups and retracted_signups:
            status = "mixed"
            status_label = "Teilweise zurückgenommen"
        elif active_signups:
            status = "booked"
            status_label = "Gebucht"
        elif retracted_signups:
            status = "retracted"
            status_label = "Zurückgenommen"
        elif locked:
            status = "closed"
            status_label = "Geschlossen"
        else:
            status = "empty"
            status_label = "Ungebucht"
        price_rule = _meal_price_rule_for_targets(camp, meal, meal_date, participant, meal_targets)
        slot = {
            "meal": meal,
            "label": meal_labels[meal],
            "status": status,
            "status_label": status_label,
            "signups": scoped,
            "active_signups": active_signups,
            "active_signup_names": [
                signup.family_member.full_name if signup.family_member_id else signup.participant.full_name
                for signup in active_signups
            ],
            "retracted_signups": retracted_signups,
            "locked": locked,
            "lock_message": lock_message,
            "description": menu_descriptions.get(meal_date, ""),
            "price_rule": price_rule,
            "unit_price": price_rule.unit_price if price_rule else None,
            "dialog_id": "meal-dialog" if meal == MealSignup.Meal.DINNER else "breakfast-meal-dialog",
        }
        meals.append(slot)
        days.append(
            {
                "date": meal_date,
                "status": slot["status"],
                "status_label": slot["status_label"],
                "locked": slot["locked"],
                "lock_message": slot["lock_message"],
                "price_rule": slot["price_rule"],
                "unit_price": slot["unit_price"],
                "description": slot["description"],
                "meals": meals,
            }
        )
    return days


def _group_kiosk_meal_calendar(days):
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    return {
        "past": [day for day in days if day["date"] < today],
        "current": [day for day in days if today <= day["date"] <= tomorrow],
        "future": [day for day in days if day["date"] > tomorrow],
    }


@meal_manager_required
def meal_cutoff_edit(request, camp_id):
    """Edit only the meal booking cutoff for a camp."""
    camp = get_object_or_404(Camp, pk=camp_id)
    form = MealCutoffForm(request.POST or None, instance=camp)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Essens-Stichzeitpunkt wurde gespeichert.")
        return redirect("camp-meal-overview", camp_id=camp.pk)
    return render(
        request, "billing/form.html", {"form": form, "title": "Essens-Stichzeitpunkt bearbeiten", "camp": camp}
    )


@meal_manager_required
def camp_meal_overview(request, camp_id):
    """Render the per-day meal counts used for caterer ordering."""
    camp = get_object_or_404(Camp, pk=camp_id)
    next_order_date = next_catering_order_date()
    meal_overview_days = calculate_meal_overview(camp)
    meal_dates = [day.meal_date for day in meal_overview_days]
    meal_plan_form_data = (
        request.POST if request.method == "POST" and request.POST.get("action") == "meal_plan" else None
    )
    meal_plan_form = MealPlanForm(meal_plan_form_data, camp=camp, meal_dates=meal_dates, prefix="meal_plan")
    if request.method == "POST" and request.POST.get("action") == "meal_plan":
        if meal_plan_form.is_valid():
            meal_plan_form.save()
            messages.success(request, "Speiseplan wurde gespeichert.")
            return redirect("camp-meal-overview", camp_id=camp.pk)
    meal_plan_rows = [
        {
            "day": day,
            "description_field": meal_plan_form[MealPlanForm.field_name(day.meal_date)],
        }
        for day in meal_overview_days
    ]
    return render(
        request,
        "billing/camp_meal_overview.html",
        {
            "camp": camp,
            "meal_overview_days": meal_overview_days,
            "meal_plan_form": meal_plan_form,
            "meal_plan_rows": meal_plan_rows,
            "next_order_day": next((day for day in meal_overview_days if day.meal_date == next_order_date), None),
            "next_order_date": next_order_date,
            "next_meal_order": meal_order_for_date(camp, next_order_date),
        },
    )


@meal_manager_required
@require_POST
def meal_order_mark_sent(request, camp_id):
    """Mark tomorrow's catering meal order as sent."""
    camp = get_object_or_404(Camp, pk=camp_id)
    meal_date = next_catering_order_date()
    MealOrder.objects.update_or_create(
        camp=camp,
        meal_date=meal_date,
        defaults={"ordered_at": timezone.now(), "ordered_by": request.user},
    )
    messages.success(request, f"Essensbestellung für {meal_date:%d.%m.%Y} wurde als abgeschickt markiert.")
    return redirect("camp-meal-overview", camp_id=camp.pk)


def kiosk_home(request, kiosk_mode="private"):
    """Render and process participant kiosk workflows for the selected device mode."""
    _activate_kiosk_mode(request, kiosk_mode)
    participant = _kiosk_participant(request)
    if participant is None:
        return redirect(_kiosk_route(kiosk_mode, "login"))

    is_pre_camp = participant.camp.is_pre_camp()
    is_post_camp = participant.camp.is_post_camp()
    active_family_member = _kiosk_family_member(request, participant)
    default_booking_target = active_family_member or participant
    default_booking_target_token = (
        f"family-{active_family_member.pk}" if active_family_member is not None else f"participant-{participant.pk}"
    )
    next_order_date = next_catering_order_date()
    next_meal_order = meal_order_for_date(participant.camp, next_order_date)
    family_members = list(
        participant.family_members.select_related("pin").filter(is_active=True).order_by("last_name", "first_name")
    )
    linked_participants = _linked_booking_participants(participant)
    linked_participant_ids = [linked_participant.pk for linked_participant in linked_participants]
    linked_participant_id_set = set(linked_participant_ids)
    meal_targets = _kiosk_meal_targets(
        participant,
        family_members=family_members,
        linked_participants=linked_participants,
    )
    quick_booking_target_groups = set()
    for target in meal_targets:
        if target["is_child"]:
            quick_booking_target_groups.add("child")
        elif target["is_companion"]:
            quick_booking_target_groups.add("companion")
        else:
            quick_booking_target_groups.add("adult")
    checkin_participants = _kiosk_checkin_participants(
        participant,
        family_members=family_members,
        linked_participants=linked_participants,
    )
    quick_form = QuickBookingForm(
        participant=participant,
        target_groups=quick_booking_target_groups,
        prefix="quick",
    )
    meal_form = MealBookingForm(participant=participant, prefix="meal")
    family_member_form = KioskFamilyMemberForm(prefix="family")
    family_member_pin_form = None
    family_member_pin_member_id = None
    actor_pin = active_family_member.pin if active_family_member is not None else participant.pin
    pin_change_form = KioskPinChangeForm(pin_record=actor_pin, prefix="pin")
    quick_confirmation = None
    if request.method == "POST":
        action = request.POST.get("action")
        if is_post_camp and action not in POST_CAMP_KIOSK_ACTIONS:
            messages.error(request, "Das Lager ist beendet. Änderungen sind nicht mehr möglich.")
            return redirect(_kiosk_route(kiosk_mode, "home"))
        if is_pre_camp and action not in PRE_CAMP_KIOSK_ACTIONS:
            messages.error(request, "Diese Funktion ist erst ab Lagerbeginn verfügbar.")
            return redirect(_kiosk_route(kiosk_mode, "home"))
        if active_family_member is not None and action in GUARDIAN_ONLY_KIOSK_ACTIONS:
            return HttpResponseForbidden("Nur Hauptteilnehmer dürfen Familienmitglieder verwalten.")
        if action == "pin_change":
            pin_model = ParticipantFamilyMemberPin if active_family_member is not None else ParticipantPin
            pin_changed = False
            with transaction.atomic():
                locked_pin = pin_model.objects.select_for_update().get(pk=actor_pin.pk)
                pin_change_form = KioskPinChangeForm(request.POST, pin_record=locked_pin, prefix="pin")
                if pin_change_form.is_valid():
                    locked_pin.set_pin(pin_change_form.cleaned_data["pin"])
                    locked_pin.save()
                    pin_changed = True
            if pin_changed:
                _clear_kiosk_session(request)
                messages.success(request, "Deine PIN wurde geändert. Bitte melde dich erneut an.")
                return redirect(_kiosk_route(kiosk_mode, "login"))
        elif action == "quick":
            quick_form = QuickBookingForm(
                request.POST,
                participant=participant,
                target_groups=quick_booking_target_groups,
                prefix="quick",
            )
            if quick_form.is_valid():
                target_ids = list(dict.fromkeys(request.POST.getlist("quick-target")))
                targets_by_token = _target_lookup(meal_targets)
                if not target_ids and request.POST.get("quick-targets-submitted") != "1":
                    target_ids = [default_booking_target_token]
                if any(target_id not in targets_by_token for target_id in target_ids):
                    quick_form.add_error(None, "Mindestens eine ausgewählte Person ist nicht verfügbar.")
                selected_targets = [
                    targets_by_token[target_id]["object"] for target_id in target_ids if target_id in targets_by_token
                ]
                if not selected_targets:
                    quick_form.add_error(None, "Bitte mindestens eine Person auswählen.")

                rule = quick_form.cleaned_data["price_rule"]
                occurred_on = timezone.localdate()
                resolved_bookings = []
                for target in selected_targets:
                    if isinstance(target, ParticipantFamilyMember):
                        charge_participant = target.guardian
                        target_family_member = target
                        target_is_child = target.is_child
                        target_is_companion = target.role == target.Role.COMPANION
                    else:
                        charge_participant = target
                        target_family_member = None
                        target_is_child = target.is_child
                        target_is_companion = target.is_companion
                    effective_rule = resolve_quick_booking_price_rule(
                        rule,
                        occurred_on,
                        is_child=target_is_child,
                        is_companion=target_is_companion,
                    )
                    if effective_rule is None:
                        quick_form.add_error(
                            "price_rule",
                            "Die Preisregel ist nicht für alle ausgewählten Personen verfügbar.",
                        )
                        break
                    resolved_bookings.append(
                        (
                            target,
                            charge_participant,
                            target_family_member,
                            effective_rule,
                        )
                    )

                confirmation_requested = request.POST.get("quick-confirmed") == "1"
                requires_confirmation = len(resolved_bookings) > 1 or confirmation_requested
                confirmation_matches = False
                confirmation_nonce = None
                if not quick_form.errors and requires_confirmation:
                    quantity = quick_form.cleaned_data["quantity"]
                    confirmation_items = [
                        {
                            "name": target.full_name,
                            "price_rule_name": effective_rule.name,
                            "quantity": quantity,
                            "unit_price": effective_rule.unit_price,
                            "total": effective_rule.unit_price * quantity,
                        }
                        for target, _, _, effective_rule in resolved_bookings
                    ]
                    confirmation_payload = _kiosk_quick_confirmation_payload(
                        participant=participant,
                        selected_rule=rule,
                        quantity=quantity,
                        occurred_on=occurred_on,
                        target_ids=target_ids,
                        resolved_bookings=resolved_bookings,
                    )
                    if confirmation_requested:
                        confirmation_nonce = _kiosk_quick_confirmation_nonce(
                            request.POST.get("quick-confirmation-token", ""),
                            confirmation_payload,
                        )
                        confirmation_matches = confirmation_nonce is not None
                    if not confirmation_matches:
                        quick_confirmation = {
                            "price_rule_id": rule.pk,
                            "quantity": quantity,
                            "target_tokens": target_ids,
                            "items": confirmation_items,
                            "total": sum(
                                (item["total"] for item in confirmation_items),
                                Decimal("0.00"),
                            ),
                            "token": _sign_kiosk_quick_confirmation(confirmation_payload),
                            "changed": confirmation_requested,
                        }
                if not quick_form.errors and (not requires_confirmation or confirmation_matches):
                    if (
                        confirmation_nonce is not None
                        and Charge.objects.filter(kiosk_confirmation_nonce=confirmation_nonce).exists()
                    ):
                        messages.info(request, "Diese Bestätigung wurde bereits verarbeitet.")
                        return redirect(_kiosk_route(kiosk_mode, "home"))
                    try:
                        with transaction.atomic():
                            booking_participants = [booking[1] for booking in resolved_bookings]
                            booking_family_members = [
                                active_family_member,
                                *(booking[2] for booking in resolved_bookings),
                            ]
                            expected_participant_ids = {participant.pk, *(item.pk for item in booking_participants)}
                            expected_family_member_ids = {
                                member.pk for member in booking_family_members if member is not None
                            }
                            locked_camp, locked_participants, locked_family_members = (
                                _lock_booking_authorization_dependencies(
                                    [participant, *booking_participants],
                                    booking_family_members,
                                    camp=participant.camp,
                                )
                            )
                            if (
                                set(locked_participants) != expected_participant_ids
                                or set(locked_family_members) != expected_family_member_ids
                            ):
                                raise PermissionDenied("Das Buchungsziel ist nicht mehr verfügbar.")
                            locked_actor = locked_participants[participant.pk]
                            locked_actor_family_member = (
                                locked_family_members[active_family_member.pk]
                                if active_family_member is not None
                                else None
                            )
                            locked_price_rules = _lock_kiosk_price_rules(locked_camp)
                            locked_selected_rule = locked_price_rules.get(rule.pk)
                            if (
                                locked_selected_rule is None
                                or locked_selected_rule.is_archived
                                or _kiosk_price_rule_state(locked_selected_rule) != _kiosk_price_rule_state(rule)
                            ):
                                raise PermissionDenied("Die Preisregel wurde zwischenzeitlich geändert.")
                            locked_resolved_bookings = []
                            for _target, charge_participant, target_family_member, effective_rule in resolved_bookings:
                                locked_charge_participant = locked_participants[charge_participant.pk]
                                locked_target_family_member = (
                                    locked_family_members[target_family_member.pk]
                                    if target_family_member is not None
                                    else None
                                )
                                locked_target = locked_target_family_member or locked_charge_participant
                                if locked_target_family_member is not None:
                                    target_is_child = locked_target_family_member.is_child
                                    target_is_companion = (
                                        locked_target_family_member.role == ParticipantFamilyMember.Role.COMPANION
                                    )
                                else:
                                    target_is_child = locked_charge_participant.is_child
                                    target_is_companion = locked_charge_participant.is_companion
                                current_effective_rule = resolve_quick_booking_price_rule(
                                    locked_selected_rule,
                                    occurred_on,
                                    is_child=target_is_child,
                                    is_companion=target_is_companion,
                                )
                                locked_effective_rule = (
                                    locked_price_rules.get(current_effective_rule.pk)
                                    if current_effective_rule is not None
                                    else None
                                )
                                if locked_effective_rule is None or _kiosk_price_rule_state(
                                    locked_effective_rule
                                ) != _kiosk_price_rule_state(effective_rule):
                                    raise PermissionDenied("Die Preisregel wurde zwischenzeitlich geändert.")
                                locked_resolved_bookings.append(
                                    (
                                        locked_target,
                                        locked_charge_participant,
                                        locked_target_family_member,
                                        locked_effective_rule,
                                    )
                                )
                            locked_booking_links = _lock_accepted_booking_links(
                                locked_actor,
                                [booking[1] for booking in locked_resolved_bookings],
                                family_members=[
                                    locked_actor_family_member,
                                    *(booking[2] for booking in locked_resolved_bookings),
                                ],
                                dependencies_locked=True,
                            )
                            for booking_index, (
                                target,
                                charge_participant,
                                target_family_member,
                                effective_rule,
                            ) in enumerate(locked_resolved_bookings):
                                booking_link = None
                                if charge_participant.pk != locked_actor.pk:
                                    booking_link = locked_booking_links.get(charge_participant.pk)
                                    if booking_link is None:
                                        raise PermissionDenied("Die Partner-Vollmacht ist nicht mehr aktiv.")
                                charge_desc = f"{effective_rule.name} (Kiosk)"
                                if target != locked_actor:
                                    charge_desc = f"{effective_rule.name} (Kiosk) für {target.full_name}"

                                charge = Charge(
                                    participant=charge_participant,
                                    kind=(
                                        Charge.Kind.DRINK
                                        if effective_rule.kind == PriceRule.Kind.DRINK
                                        else Charge.Kind.FOOD
                                    ),
                                    description=charge_desc,
                                    quantity=quick_form.cleaned_data["quantity"],
                                    unit_price=effective_rule.unit_price,
                                    foerdersatz=effective_rule.foerdersatz,
                                    occurred_on=occurred_on,
                                    kiosk_booked_by=locked_actor,
                                    kiosk_confirmation_nonce=(confirmation_nonce if booking_index == 0 else None),
                                )
                                charge.save()
                                if booking_link is not None or target_family_member is not None:
                                    create_kiosk_action_audit_log(
                                        camp=locked_camp,
                                        actor_participant=locked_actor,
                                        actor_family_member=locked_actor_family_member,
                                        target_participant=charge_participant,
                                        target_family_member=target_family_member,
                                        booking_link=booking_link,
                                        charge=charge,
                                        action=KioskActionAuditLog.Action.QUICK_BOOKED,
                                        description=f"{charge.booking_reference}: Schnellbuchung erstellt.",
                                        before={},
                                        after=kiosk_charge_audit_snapshot(charge),
                                    )
                                transaction.on_commit(
                                    partial(
                                        _notify_linked_booking_by_id,
                                        charge.pk,
                                        locked_actor.pk,
                                        actor_display_name=(
                                            locked_actor_family_member.full_name
                                            if locked_actor_family_member is not None
                                            else locked_actor.full_name
                                        ),
                                        cancelled=False,
                                    )
                                )
                    except IntegrityError:
                        if (
                            confirmation_nonce is None
                            or not Charge.objects.filter(kiosk_confirmation_nonce=confirmation_nonce).exists()
                        ):
                            raise
                        messages.info(request, "Diese Bestätigung wurde bereits verarbeitet.")
                        return redirect(_kiosk_route(kiosk_mode, "home"))
                    messages.success(request, f"{rule.name} gebucht.")
                    return redirect(_kiosk_route(kiosk_mode, "home"))
        elif request.POST.get("action") == "quick_cancel":
            try:
                charge_id = int(request.POST.get("charge_id", ""))
            except ValueError:
                charge_id = None
            with transaction.atomic():
                submitted_charge = (
                    Charge.objects.annotate(
                        has_meal_signup=Exists(
                            MealSignup.objects.filter(charge_id=OuterRef("pk")),
                        )
                    )
                    .select_related("participant")
                    .filter(
                        Q(participant=participant)
                        | Q(kiosk_booked_by=participant)
                        | Q(participant_id__in=linked_participant_ids),
                        pk=charge_id,
                        kind__in=[Charge.Kind.DRINK, Charge.Kind.FOOD],
                        deleted_at__isnull=True,
                        has_meal_signup=False,
                    )
                    .first()
                )
                if submitted_charge is None:
                    messages.error(request, "Diese Buchung kann nicht mehr storniert werden.")
                else:
                    creation_audit = (
                        KioskActionAuditLog.objects.select_related(
                            "booking_link",
                            "target_family_member",
                        )
                        .filter(
                            charge=submitted_charge,
                            action=KioskActionAuditLog.Action.QUICK_BOOKED,
                        )
                        .order_by("created_at", "pk")
                        .first()
                    )
                    submitted_target_family_member = (
                        creation_audit.target_family_member if creation_audit is not None else None
                    )
                    dependency_participants = [participant, submitted_charge.participant]
                    dependency_family_members = [active_family_member, submitted_target_family_member]
                    expected_participant_ids = {item.pk for item in dependency_participants}
                    expected_family_member_ids = {item.pk for item in dependency_family_members if item is not None}
                    locked_camp, locked_participants, locked_family_members = _lock_booking_authorization_dependencies(
                        dependency_participants,
                        dependency_family_members,
                        camp=participant.camp,
                    )
                    if (
                        set(locked_participants) != expected_participant_ids
                        or set(locked_family_members) != expected_family_member_ids
                    ):
                        raise PermissionDenied("Diese Buchung kann nicht mehr storniert werden.")
                    locked_actor = locked_participants[participant.pk]
                    locked_target_participant = locked_participants[submitted_charge.participant_id]
                    locked_actor_family_member = (
                        locked_family_members[active_family_member.pk] if active_family_member is not None else None
                    )
                    locked_target_family_member = (
                        locked_family_members[submitted_target_family_member.pk]
                        if submitted_target_family_member is not None
                        else None
                    )
                    charge = (
                        Charge.objects.select_for_update(of=("self",))
                        .annotate(
                            has_meal_signup=Exists(
                                MealSignup.objects.filter(charge_id=OuterRef("pk")),
                            )
                        )
                        .filter(
                            pk=submitted_charge.pk,
                            participant_id=submitted_charge.participant_id,
                            kiosk_booked_by_id=submitted_charge.kiosk_booked_by_id,
                            kind__in=[Charge.Kind.DRINK, Charge.Kind.FOOD],
                            deleted_at__isnull=True,
                            has_meal_signup=False,
                        )
                        .first()
                    )
                    if charge is None or not _is_kiosk_quick_charge_cancelable(
                        charge,
                        locked_actor,
                        authorized_participant_ids=linked_participant_id_set,
                    ):
                        messages.error(request, "Diese Buchung kann nicht mehr storniert werden.")
                    else:
                        booking_link = None
                        if charge.participant_id != locked_actor.pk:
                            booking_link = _lock_accepted_booking_links(
                                locked_actor,
                                [locked_target_participant],
                                family_members=[
                                    locked_actor_family_member,
                                    locked_target_family_member,
                                ],
                                dependencies_locked=True,
                            ).get(charge.participant_id)
                            if booking_link is None:
                                raise PermissionDenied("Die Partner-Vollmacht ist nicht mehr aktiv.")
                        elif charge.kiosk_booked_by_id != locked_actor.pk:
                            booking_link = creation_audit.booking_link if creation_audit is not None else None
                        before = kiosk_charge_audit_snapshot(charge)
                        charge.deleted_at = timezone.now()
                        charge.deleted_by = None
                        charge.save(update_fields=["deleted_at", "deleted_by"])
                        audit_log = None
                        partner_action = charge.participant_id != locked_actor.pk
                        if partner_action or charge.kiosk_booked_by_id != charge.participant_id:
                            audit_log = create_kiosk_action_audit_log(
                                camp=locked_camp,
                                actor_participant=locked_actor,
                                actor_family_member=locked_actor_family_member,
                                target_participant=locked_target_participant,
                                target_family_member=locked_target_family_member,
                                booking_link=booking_link,
                                charge=charge,
                                action=KioskActionAuditLog.Action.QUICK_CANCELLED,
                                description=f"{charge.booking_reference}: Schnellbuchung storniert.",
                                before=before,
                                after=kiosk_charge_audit_snapshot(charge),
                            )
                        if audit_log is not None and partner_action:
                            transaction.on_commit(partial(_notify_kiosk_partner_action_by_id, audit_log.pk))
                        else:
                            transaction.on_commit(
                                partial(
                                    _notify_linked_booking_by_id,
                                    charge.pk,
                                    locked_actor.pk,
                                    actor_display_name=(
                                        locked_actor_family_member.full_name
                                        if locked_actor_family_member is not None
                                        else locked_actor.full_name
                                    ),
                                    cancelled=True,
                                )
                            )
                        messages.success(request, "Buchung wurde storniert.")
                        return redirect(_kiosk_route(kiosk_mode, "home"))
        elif request.POST.get("action") == "meal":
            meal_form = MealBookingForm(request.POST, participant=participant, prefix="meal")
            if meal_form.is_valid():
                meal_dates = meal_form.cleaned_data["meal_dates"]
                meal = meal_form.cleaned_data["meal"]
                sent_order_dates = set(
                    MealOrder.objects.filter(camp=participant.camp, meal_date__in=meal_dates).values_list(
                        "meal_date", flat=True
                    )
                )
                for meal_date in meal_dates:
                    if is_meal_change_locked(
                        participant.camp,
                        meal_date,
                        sent_order_dates=sent_order_dates,
                    ):
                        meal_form.add_error(
                            None,
                            meal_change_lock_message(
                                participant.camp,
                                meal_date,
                                sent_order_dates=sent_order_dates,
                            ),
                        )
                selected_tokens = list(dict.fromkeys(request.POST.getlist("meal-target")))
                targets_by_token = _target_lookup(meal_targets)
                if not selected_tokens and request.POST.get("meal-targets-submitted") != "1":
                    selected_tokens = [default_booking_target_token]
                if any(token not in targets_by_token for token in selected_tokens):
                    meal_form.add_error(None, "Mindestens eine ausgewählte Person ist nicht verfügbar.")
                selected_targets = [targets_by_token[token] for token in selected_tokens if token in targets_by_token]
                if not selected_targets:
                    meal_form.add_error(None, "Bitte mindestens eine Person auswählen.")
                missing_prices = []
                invalid_variants = []
                bookings = []
                for target in selected_targets:
                    variant = request.POST.get(f"meal-variant-{target['token']}") or meal_form.cleaned_data["variant"]
                    valid_variants = {choice[0] for choice in target["variant_choices"]}
                    if variant not in valid_variants:
                        invalid_variants.append(target["name"])
                        continue
                    for meal_date in meal_dates:
                        price_rule = resolve_meal_price_rule(
                            participant.camp,
                            meal,
                            meal_date,
                            is_child=target["is_child"],
                            is_companion=target["is_companion"],
                        )
                        if price_rule is None:
                            missing_prices.append(f"{target['name']} am {meal_date:%d.%m.%Y}")
                            continue
                        bookings.append((target, meal_date, variant, price_rule))
                if invalid_variants:
                    meal_form.add_error(None, "Bitte für jede ausgewählte Person eine gültige Variante auswählen.")
                if missing_prices:
                    meal_form.add_error(
                        None,
                        "Für diese Mahlzeit ist kein Preis hinterlegt: " + ", ".join(missing_prices),
                    )
                if not meal_form.errors:
                    with transaction.atomic():
                        booking_participants = [
                            target["object"] if target["kind"] == "participant" else target["object"].guardian
                            for target, _meal_date, _variant, _price_rule in bookings
                        ]
                        booking_family_members = [active_family_member]
                        booking_family_members.extend(
                            target["object"]
                            for target, _meal_date, _variant, _price_rule in bookings
                            if target["kind"] == "family"
                        )
                        expected_participant_ids = {participant.pk, *(item.pk for item in booking_participants)}
                        expected_family_member_ids = {
                            member.pk for member in booking_family_members if member is not None
                        }
                        _locked_camp, locked_participants, locked_family_members = (
                            _lock_booking_authorization_dependencies(
                                [participant, *booking_participants],
                                booking_family_members,
                                camp=participant.camp,
                            )
                        )
                        if (
                            set(locked_participants) != expected_participant_ids
                            or set(locked_family_members) != expected_family_member_ids
                        ):
                            raise PermissionDenied("Das Buchungsziel ist nicht mehr verfügbar.")
                        locked_actor = locked_participants[participant.pk]
                        locked_actor_family_member = (
                            locked_family_members[active_family_member.pk] if active_family_member is not None else None
                        )
                        locked_booking_participants = [locked_participants[item.pk] for item in booking_participants]
                        locked_booking_family_members = [
                            locked_family_members[member.pk] for member in booking_family_members if member is not None
                        ]
                        locked_price_rules = _lock_kiosk_price_rules(_locked_camp)
                        locked_bookings = []
                        for target, meal_date, variant, submitted_price_rule in bookings:
                            target_object = target["object"]
                            locked_target_object = (
                                locked_participants[target_object.pk]
                                if target["kind"] == "participant"
                                else locked_family_members[target_object.pk]
                            )
                            locked_target = {**target, "object": locked_target_object}
                            locked_price_rule = _revalidate_locked_meal_price_rule(
                                locked_price_rules=locked_price_rules,
                                submitted_price_rule=submitted_price_rule,
                                camp=_locked_camp,
                                meal=meal,
                                meal_date=meal_date,
                                is_child=locked_target_object.is_child,
                                is_companion=(
                                    locked_target_object.role == ParticipantFamilyMember.Role.COMPANION
                                    if isinstance(locked_target_object, ParticipantFamilyMember)
                                    else locked_target_object.is_companion
                                ),
                            )
                            locked_bookings.append((locked_target, meal_date, variant, locked_price_rule))
                        locked_signups, created_signup_keys = _lock_meal_signups_for_bookings(
                            locked_bookings,
                            meal,
                        )
                        locked_booking_links = _lock_accepted_booking_links(
                            locked_actor,
                            locked_booking_participants,
                            family_members=locked_booking_family_members,
                            dependencies_locked=True,
                        )
                        for target, meal_date, variant, price_rule in locked_bookings:
                            signup_key = _meal_signup_key(target, meal_date, meal)
                            target_object = target["object"]
                            target_participant_id = (
                                target_object.pk if target["kind"] == "participant" else target_object.guardian_id
                            )
                            _book_meal_for_target(
                                target,
                                meal_date,
                                meal,
                                variant,
                                price_rule,
                                locked_actor,
                                locked_actor_family_member,
                                prelocked_signup=locked_signups.get(signup_key),
                                signup_lock_acquired=True,
                                signup_was_created=signup_key in created_signup_keys,
                                prelocked_booking_link=locked_booking_links.get(target_participant_id),
                                booking_link_lock_acquired=True,
                                dependencies_lock_acquired=True,
                                price_rule_lock_acquired=True,
                            )
                    day_label = "Tag" if len(meal_dates) == 1 else "Tage"
                    person_label = "Person" if len(selected_targets) == 1 else "Personen"
                    messages.success(
                        request,
                        f"Essensanmeldung wurde für {len(meal_dates)} {day_label} und "
                        f"{len(selected_targets)} {person_label} gespeichert.",
                    )
                    return redirect(f"{reverse(_kiosk_route(kiosk_mode, 'home'))}?dialog=meal-calendar")
        elif request.POST.get("action") == "meal_retract":
            signup_id = _positive_int_or_none(request.POST.get("meal_signup_id"))
            targets_by_token = _target_lookup(meal_targets)
            signup = None
            if signup_id is not None:
                signup = (
                    MealSignup.objects.select_related("participant", "family_member", "charge")
                    .filter(pk=signup_id, status=MealSignup.Status.ACTIVE)
                    .first()
                )
            if signup is None or _target_token_for_signup(signup) not in targets_by_token:
                messages.error(request, "Essensanmeldung wurde nicht gefunden.")
            elif is_meal_change_locked(participant.camp, signup.meal_date):
                messages.error(request, meal_change_lock_message(participant.camp, signup.meal_date))
            elif signup.participant_id != participant.pk and not _matches_kiosk_meal_retraction(
                request.POST.get("meal_retraction_token", ""),
                participant,
                signup,
            ):
                messages.error(
                    request,
                    "Bitte bestätige die Rücknahme der Partner-Essensanmeldung erneut.",
                )
            else:
                with transaction.atomic():
                    retracted = _retract_meal_signup(
                        signup,
                        participant,
                        active_family_member,
                        confirmation_token=request.POST.get("meal_retraction_token", ""),
                    )
                if retracted:
                    messages.success(request, "Essensanmeldung wurde zurückgenommen.")
                    return redirect(_kiosk_route(kiosk_mode, "home"))
                messages.error(
                    request,
                    "Essensanmeldung wurde zwischenzeitlich geändert. Bitte lade die Seite neu und bestätige erneut.",
                )
        elif request.POST.get("action") == "family_member_create":
            family_member_form = KioskFamilyMemberForm(request.POST, prefix="family")
            if family_member_form.is_valid():
                with transaction.atomic():
                    family_member = family_member_form.save(commit=False)
                    family_member.guardian = participant
                    family_member.save()
                    if family_member.role == ParticipantFamilyMember.Role.COMPANION:
                        family_member.pin.set_pin(family_member_form.cleaned_data["pin"])
                        family_member.pin.save()
                messages.success(request, "Familienmitglied wurde angelegt.")
                return redirect(_kiosk_route(kiosk_mode, "home"))
        elif request.POST.get("action") == "family_member_pin_set":
            family_member_pin_member_id = _positive_int_or_none(request.POST.get("family_member_id"))
            family_member = None
            if family_member_pin_member_id is not None:
                family_member = (
                    participant.family_members.select_related("pin")
                    .filter(
                        pk=family_member_pin_member_id,
                        role=ParticipantFamilyMember.Role.COMPANION,
                        is_active=True,
                    )
                    .first()
                )
            if family_member is None:
                messages.error(request, "Begleitperson wurde nicht gefunden.")
            else:
                family_member_pin_form = KioskFamilyMemberPinForm(request.POST, prefix="family")
                if family_member_pin_form.is_valid():
                    with transaction.atomic():
                        family_member.pin.set_pin(family_member_pin_form.cleaned_data["pin"])
                        family_member.pin.save()
                    messages.success(request, f"PIN für {family_member.full_name} wurde gespeichert.")
                    return redirect(_kiosk_route(kiosk_mode, "home"))
        elif request.POST.get("action") == "family_member_deactivate":
            member_id = _positive_int_or_none(request.POST.get("family_member_id"))
            family_member = None
            if member_id is not None:
                family_member = participant.family_members.filter(pk=member_id, is_active=True).first()
            if family_member is not None:
                family_member.is_active = False
                family_member.save(update_fields=["is_active", "updated_at"])
                messages.success(request, "Familienmitglied wurde entfernt.")
                return redirect(_kiosk_route(kiosk_mode, "home"))
            messages.error(request, "Familienmitglied wurde nicht gefunden.")
        elif request.POST.get("action") == "checkin":
            if _update_kiosk_checkin_dates(request, participant, checkin_participants):
                return redirect(_kiosk_route(kiosk_mode, "home"))
        elif request.POST.get("action") == "update_attendance_dates":
            arrival_str = request.POST.get("arrival_date", "")
            departure_str = request.POST.get("departure_date", "")
            try:
                arrival = datetime.strptime(arrival_str, "%Y-%m-%d").date() if arrival_str else None
                departure = datetime.strptime(departure_str, "%Y-%m-%d").date() if departure_str else None
                if arrival and departure and departure < arrival:
                    messages.error(request, "Das Abreisedatum darf nicht vor dem Anreisedatum liegen.")
                    return redirect(_kiosk_route(kiosk_mode, "home"))
                if arrival:
                    participant.arrival_date = arrival
                if departure:
                    participant.departure_date = departure
                if (
                    participant.arrival_date
                    and participant.departure_date
                    and participant.departure_date >= participant.arrival_date
                ):
                    participant.booked_nights = (participant.departure_date - participant.arrival_date).days
                participant.save(update_fields=["arrival_date", "departure_date", "booked_nights", "updated_at"])
                messages.success(request, "Anmeldezeitraum wurde aktualisiert.")
            except (ValueError, TypeError):
                messages.error(request, "Ungültiges Datumsformat.")
            return redirect(_kiosk_route(kiosk_mode, "home"))
        elif action == "donate":
            try:
                amount = Decimal(request.POST.get("donation_amount", "0").replace(",", "."))
                if amount > 0:
                    with transaction.atomic():
                        Charge.objects.create(
                            participant=participant,
                            kind=Charge.Kind.DONATION,
                            description="Spende am Kiosk",
                            quantity=1,
                            unit_price=amount,
                            kiosk_booked_by=default_booking_target,
                            occurred_on=timezone.localdate(),
                        )
                        create_kiosk_action_audit_log(
                            camp=participant.camp,
                            action=KioskActionAuditLog.Action.QUICK_BOOKED,
                            actor_participant=participant if active_family_member is None else None,
                            actor_family_member=active_family_member,
                            target_participant=participant,
                            description=f"Spende erfasst (Betrag: {amount:.2f} €)",
                        )
                    messages.success(request, f"Vielen Dank für deine Spende von {amount:.2f} €!")
                    request.session["show_party_animation"] = True
                else:
                    messages.error(request, "Bitte einen Betrag größer als 0 eingeben.")
            except (ValueError, InvalidOperation):
                messages.error(request, "Ungültiger Betrag eingegeben.")
            return redirect(_kiosk_route(kiosk_mode, "home"))

    recent_quick_charges = list(
        Charge.objects.annotate(
            has_meal_signup=Exists(
                MealSignup.objects.filter(charge_id=OuterRef("pk")),
            )
        )
        .select_related("participant", "kiosk_booked_by")
        .filter(
            Q(participant=participant) | Q(kiosk_booked_by=participant) | Q(participant_id__in=linked_participant_ids),
            kind__in=[Charge.Kind.DRINK, Charge.Kind.FOOD],
            deleted_at__isnull=True,
            kiosk_booked_by__isnull=False,
            has_meal_signup=False,
        )
        .distinct()
        .order_by("-created_at")[:8]
    )
    quick_cancel_now = timezone.now()
    for charge in recent_quick_charges:
        charge.is_kiosk_cancelable = _is_kiosk_quick_charge_cancelable(
            charge,
            participant,
            quick_cancel_now,
            authorized_participant_ids=linked_participant_id_set,
        )
    meal_signups = (
        MealSignup.objects.select_related("participant", "family_member", "charge")
        .filter(Q(participant=participant) | Q(participant_id__in=linked_participant_ids))
        .order_by("meal_date", "meal", "participant__last_name", "participant__first_name")
    )
    meal_signups = list(meal_signups)
    for signup in meal_signups:
        signup.requires_partner_retraction_confirmation = signup.participant_id != participant.pk
        signup.retraction_confirmation_token = (
            _sign_kiosk_meal_retraction(participant, signup) if signup.requires_partner_retraction_confirmation else ""
        )
    dinner_calendar_days = _kiosk_meal_calendar(
        participant.camp, participant, meal_signups, meal_targets, meal=MealSignup.Meal.DINNER
    )
    breakfast_calendar_days = _kiosk_meal_calendar(
        participant.camp, participant, meal_signups, meal_targets, meal=MealSignup.Meal.BREAKFAST
    )
    meal_calendar_days = dinner_calendar_days
    is_meal_post = request.method == "POST" and request.POST.get("action") == "meal"
    selected_meal_date_values = set(request.POST.getlist(meal_form.add_prefix("meal_dates"))) if is_meal_post else set()
    for meal_calendar_day in meal_calendar_days:
        meal_calendar_day["selected"] = meal_calendar_day["date"].isoformat() in selected_meal_date_values
    selected_meal_target_tokens = set(request.POST.getlist("meal-target")) if is_meal_post else set()
    if not selected_meal_target_tokens and (not is_meal_post or request.POST.get("meal-targets-submitted") != "1"):
        selected_meal_target_tokens = {default_booking_target_token}
    for meal_target in meal_targets:
        meal_target["meal_selected"] = meal_target["token"] in selected_meal_target_tokens
        meal_target["selected_variant"] = (
            request.POST.get(f"meal-variant-{meal_target['token']}")
            if is_meal_post
            else meal_target["variant_choices"][0][0]
        )
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    dinner_rule = resolve_meal_price_rule(
        participant.camp,
        PriceRule.MealType.DINNER,
        next_order_date,
        is_child=participant.is_child,
        is_companion=participant.is_companion,
    )
    pending_invites = participant.received_booking_links.select_related("inviter").filter(
        status=ParticipantBookingLink.Status.PENDING,
        inviter__camp=participant.camp,
        inviter__camp__is_active=True,
        inviter__archived_at__isnull=True,
    )
    announcements = list(participant.camp.announcements.filter(is_active=True)[:3])
    historic_settlements = list(_participant_historic_settlements(participant))
    latest_settlement = historic_settlements[0] if historic_settlements else None
    archived_settlements = historic_settlements[1:] if len(historic_settlements) > 1 else []
    days_until_start = participant.camp.days_until_start()
    show_party_animation = request.session.pop("show_party_animation", False)

    context = {
        "participant": participant,
        "kiosk_actor": default_booking_target,
        "kiosk_actor_is_family_member": active_family_member is not None,
        "default_booking_target_token": default_booking_target_token,
        "announcements": announcements,
        "summary": participant_kiosk_summary(participant),
        "is_pre_camp": is_pre_camp,
        "is_post_camp": is_post_camp,
        "show_party_animation": show_party_animation,
        "days_until_start": days_until_start,
        "historic_settlements": historic_settlements,
        "latest_settlement": latest_settlement,
        "archived_settlements": archived_settlements,
        "meal_form": meal_form,
        "meal_default_variant": meal_form.fields["variant"].choices[0][0],
        "family_member_form": family_member_form,
        "family_member_pin_form": family_member_pin_form,
        "family_member_pin_member_id": family_member_pin_member_id,
        "pin_change_form": pin_change_form,
        "recent_quick_charges": recent_quick_charges,
        "meal_signups": meal_signups,
        "meal_calendar_days": dinner_calendar_days,
        "dinner_calendar_days": dinner_calendar_days,
        "breakfast_calendar_days": breakfast_calendar_days,
        "meal_calendar_groups": _group_kiosk_meal_calendar(dinner_calendar_days),
        "meal_dialog_open": is_meal_post and bool(meal_form.errors),
        "meal_dialog_step": "persons" if selected_meal_date_values else "dates",
        "drink_rules": quick_form.fields["price_rule"].queryset.filter(kind=PriceRule.Kind.DRINK),
        "snack_rules": quick_form.fields["price_rule"].queryset.filter(kind=PriceRule.Kind.MEAL),
        "dinner_rule": dinner_rule,
        "quick_form": quick_form,
        "quick_confirmation": quick_confirmation,
        "meal_targets": meal_targets,
        "checkin_participants": checkin_participants,
        "family_members": family_members,
        "pending_invites": pending_invites,
        **_kiosk_context(kiosk_mode),
        "kiosk_contacts": admin_interface_contacts(User),
        "next_order_date": next_order_date,
        "next_meal_order": next_meal_order,
        "next_order_locked": bool(next_meal_order) or is_meal_change_locked(participant.camp, next_order_date),
        "today": today,
        "tomorrow": tomorrow,
        "participant_expenses": participant.expenses.annotate(
            kiosk_status_order=Case(
                When(status=Expense.Status.PENDING, then=Value(0)),
                When(status=Expense.Status.REJECTED, then=Value(1)),
                When(status=Expense.Status.APPROVED, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        ).order_by("kiosk_status_order", "-created_at"),
    }
    return render(request, "billing/kiosk_home.html", context)


def kiosk_shared_expense_request(request, kiosk_mode="private"):
    """Create a shared-expense request from the selected kiosk mode."""
    _activate_kiosk_mode(request, kiosk_mode)
    participant = _kiosk_participant(request)
    if not participant:
        return redirect(_kiosk_route(kiosk_mode, "login"))
    if operation_redirect := _kiosk_operation_redirect(request, participant, kiosk_mode):
        return operation_redirect

    form = SharedExpenseRequestForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            expense = form.save(commit=False)
            expense.camp = participant.camp
            expense.participant = participant
            expense.reimbursable = True
            expense.save()
            transaction.on_commit(
                lambda expense_id=expense.pk: notify_expense_submitted(
                    Expense.objects.select_related("participant").get(pk=expense_id)
                )
            )
        messages.success(request, "Antrag auf Gemeinschaftsausgabe eingereicht.")
        return redirect(_kiosk_route(kiosk_mode, "home"))

    return render(
        request,
        "billing/form.html",
        {
            "form": form,
            "title": "Gemeinschaftsausgabe beantragen",
            "camp": participant.camp,
            "cancel_url": reverse(_kiosk_route(kiosk_mode, "home")),
            **_kiosk_context(kiosk_mode),
        },
    )


def kiosk_shifts(request, kiosk_mode="private"):
    """Render and process the shift exchange flow in the selected kiosk mode."""
    _activate_kiosk_mode(request, kiosk_mode)
    participant = _kiosk_participant(request)
    if not participant:
        return redirect(_kiosk_route(kiosk_mode, "login"))
    if operation_redirect := _kiosk_operation_redirect(request, participant, kiosk_mode):
        return operation_redirect

    today = timezone.localdate()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "bulk_signup":
            raw_shift_ids = request.POST.getlist("shift_ids")
            shift_ids = [_positive_int_or_none(value) for value in raw_shift_ids]
            if not raw_shift_ids:
                messages.error(request, "Bitte wähle mindestens einen Dienst aus.")
            elif any(shift_id is None for shift_id in shift_ids) or len(set(shift_ids)) != len(shift_ids):
                messages.error(request, "Die ausgewählten Dienste sind ungültig. Es wurde nichts gebucht.")
            else:
                try:
                    booked_shifts, error_message = _book_open_kiosk_shifts(
                        participant, [shift_id for shift_id in shift_ids if shift_id is not None], today
                    )
                except IntegrityError:
                    booked_shifts, error_message = (
                        [],
                        (
                            "Mindestens ein ausgewählter Dienst wurde gerade anderweitig gebucht. "
                            "Es wurde nichts gebucht."
                        ),
                    )
                if error_message:
                    messages.error(request, error_message)
                else:
                    messages.success(request, f"Du hast {len(booked_shifts)} Dienste übernommen.")
            return _kiosk_shift_redirect(request, kiosk_mode)

        shift_id = _positive_int_or_none(request.POST.get("shift_id"))
        if shift_id is None:
            messages.error(request, "Dienst wurde nicht gefunden.")
            return _kiosk_shift_redirect(request, kiosk_mode)
        shift = get_object_or_404(Shift, pk=shift_id, camp=participant.camp)

        if action == "signup":
            with transaction.atomic():
                shift = Shift.objects.select_for_update().get(pk=shift_id, camp=participant.camp)
                if ShiftAssignment.objects.filter(shift=shift, participant=participant).exists():
                    messages.error(request, "Du bist für diesen Dienst bereits eingetragen.")
                elif not shift.is_full:
                    ShiftAssignment.objects.create(shift=shift, participant=participant)
                    messages.success(request, f"Du hast dich für '{shift.name}' eingetragen.")
                else:
                    offered_assignment = (
                        shift.assignments.filter(offered_for_exchange=True).exclude(participant=participant).first()
                    )
                    if offered_assignment:
                        old_participant = offered_assignment.participant
                        offered_assignment.participant = participant
                        offered_assignment.offered_for_exchange = False
                        offered_assignment.created_at = timezone.now()
                        offered_assignment.save(
                            update_fields=["participant", "offered_for_exchange", "created_at", "updated_at"]
                        )
                        transaction.on_commit(
                            partial(
                                _notify_shift_exchange_by_id,
                                offered_assignment.pk,
                                "taken",
                                participant.pk,
                                old_participant.pk,
                            )
                        )
                        messages.success(request, f"Du hast den Dienst von {old_participant.full_name} übernommen.")
                    else:
                        messages.error(
                            request, "Dieser Dienst ist voll und es wird aktuell kein Platz zum Tausch angeboten."
                        )
        elif action == "retract":
            assignment = ShiftAssignment.objects.filter(shift=shift, participant=participant).first()
            if assignment and assignment.created_at >= timezone.now() - timedelta(minutes=15):
                assignment.delete()
                messages.success(request, f"Du hast dich aus '{shift.name}' ausgetragen.")
            else:
                messages.error(
                    request,
                    "Das Zurückziehen ist nur innerhalb von 15 Minuten nach dem Eintragen möglich. "
                    "Bitte biete deinen Dienst zum Tausch an oder wende dich an die Lagerleitung.",
                )
        elif action == "offer":
            if shift.date < today:
                messages.error(request, "Du kannst keine vergangenen Dienste zum Tausch anbieten.")
            else:
                updated = ShiftAssignment.objects.filter(shift=shift, participant=participant).update(
                    offered_for_exchange=True
                )
                if updated:
                    assignment = ShiftAssignment.objects.get(shift=shift, participant=participant)
                    transaction.on_commit(
                        partial(_notify_shift_exchange_by_id, assignment.pk, "offered", participant.pk)
                    )
                    messages.success(request, f"Dein Dienst '{shift.name}' wird nun zum Tausch angeboten.")
        elif action == "revoke_offer":
            updated = ShiftAssignment.objects.filter(shift=shift, participant=participant).update(
                offered_for_exchange=False
            )
            if updated:
                messages.success(request, f"Du hast das Tauschangebot für '{shift.name}' zurückgezogen.")

        return _kiosk_shift_redirect(request, kiosk_mode)

    shifts = (
        participant.camp.shifts.filter(date__gte=today)
        .prefetch_related("assignments__participant")
        .order_by("date", "start_time")
    )
    shift_date_filter = request.GET.get("date", "").strip()
    shift_name_filter = request.GET.get("name", "").strip()[:120]
    parsed_shift_date = parse_date(shift_date_filter) if shift_date_filter else None
    open_shifts = []
    offered_shifts = []
    my_shifts = []

    retract_cutoff = timezone.now() - timedelta(minutes=15)
    for shift in shifts:
        shift_assignments = list(shift.assignments.all())
        shift.my_assignment = next((a for a in shift_assignments if a.participant_id == participant.pk), None)
        shift.can_retract = bool(shift.my_assignment and shift.my_assignment.created_at >= retract_cutoff)
        shift.has_offers = any(a.offered_for_exchange and a.participant_id != participant.pk for a in shift_assignments)

        if shift.my_assignment:
            my_shifts.append(shift)
        elif shift.has_offers:
            offered_assignment = next(
                a for a in shift_assignments if a.offered_for_exchange and a.participant_id != participant.pk
            )
            shift.offered_by = offered_assignment.participant.full_name
            offered_shifts.append(shift)
        else:
            open_shifts.append(shift)

    shift_dates = sorted({shift.date for shift in open_shifts})
    shift_name_choices = {shift.name for shift in open_shifts}
    if shift_name_filter:
        shift_name_choices.add(shift_name_filter)
    shift_name_choices = sorted(shift_name_choices, key=str.casefold)
    if parsed_shift_date:
        open_shifts = [shift for shift in open_shifts if shift.date == parsed_shift_date]
    if shift_name_filter:
        open_shifts = [shift for shift in open_shifts if shift_name_filter.casefold() in shift.name.casefold()]

    return render(
        request,
        "billing/kiosk_shifts.html",
        {
            "participant": participant,
            "open_shifts": open_shifts,
            "offered_shifts": offered_shifts,
            "my_shifts": my_shifts,
            "shift_dates": shift_dates,
            "shift_date_filter": shift_date_filter,
            "shift_name_filter": shift_name_filter,
            "shift_name_choices": shift_name_choices,
            "today": today,
            **_kiosk_context(kiosk_mode),
        },
    )


def user_guide(request: HttpRequest) -> HttpResponse:
    """Render the built-in kiosk user documentation."""
    return render(request, "billing/user_guide.html")


@login_required
def admin_guide(request: HttpRequest) -> HttpResponse:
    """Render the built-in admin documentation."""
    return render(request, "billing/admin_guide.html")


@login_required
def debug_ip(request: HttpRequest) -> HttpResponse:
    """Debug endpoint to check proxy IPs and headers."""
    if not request.user.is_staff:
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("Only staff can view this.")

    import os

    headers_of_interest = [
        "HTTP_X_FORWARDED_FOR",
        "HTTP_X_REAL_IP",
        "HTTP_CF_CONNECTING_IP",
        "REMOTE_ADDR",
        "HTTP_FORWARDED",
        "HTTP_HOST",
    ]
    data = {k: request.META.get(k) for k in headers_of_interest}
    data["ENV_PROXY"] = os.getenv("KIOSK_ACCESS_TRUSTED_PROXY_ADDRESSES", "")
    data["ENV_GUNICORN"] = os.getenv("GUNICORN_CMD_ARGS", "")
    return JsonResponse(data)
