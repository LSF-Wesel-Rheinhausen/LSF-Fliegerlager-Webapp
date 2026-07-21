import base64
import json
import logging
from datetime import timedelta
from functools import partial
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.signing import BadSignature, Signer
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

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
    KioskLoginForm,
    KioskPinSetupForm,
    MealBookingForm,
    MealCutoffForm,
    MealPlanForm,
    MealStandardPricesForm,
    ParticipantForm,
    ParticipantImportForm,
    ParticipantPinForm,
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
from .models import (
    BookingAuditLog,
    Camp,
    Charge,
    DailySettlementBackupLog,
    DailySettlementBackupSettings,
    Expense,
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
from .notifications import notify_booking_link, notify_expense_submitted, notify_linked_booking, notify_shift_exchange
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
    create_settlement_run,
    is_meal_change_locked,
    meal_change_lock_message,
    meal_order_for_date,
    next_catering_order_date,
    participant_kiosk_summary,
    resolve_meal_price_rule,
    restore_booking_from_audit_log,
)

logger = logging.getLogger(__name__)
signer = Signer()
User = get_user_model()
KIOSK_PARTICIPANT_SESSION_KEY = "kiosk_participant_id"
KIOSK_FAMILY_MEMBER_SESSION_KEY = "kiosk_family_member_id"
KIOSK_PIN_SETUP_SESSION_KEY = "kiosk_pin_setup_participant_id"
KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY = "kiosk_pin_setup_family_member_id"
KIOSK_MODE_SESSION_KEY = "kiosk_mode"
KIOSK_QUICK_BOOKING_CANCEL_WINDOW = timedelta(minutes=15)


def kiosk_root(_request: HttpRequest) -> HttpResponse:
    """Redirect the public root to the private-device kiosk."""
    return redirect("kiosk-home")


def _kiosk_route(kiosk_mode: str, page: str) -> str:
    """Return the named route for a kiosk page in the active device mode."""
    prefix = "central-kiosk" if kiosk_mode == "central" else "kiosk"
    return f"{prefix}-{page}"


def _clear_kiosk_session(request: HttpRequest) -> None:
    """Remove every participant identity and setup value from a kiosk session."""
    for key in (
        KIOSK_PARTICIPANT_SESSION_KEY,
        KIOSK_FAMILY_MEMBER_SESSION_KEY,
        KIOSK_PIN_SETUP_SESSION_KEY,
        KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY,
    ):
        request.session.pop(key, None)


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
            "pin_setup": reverse(_kiosk_route(kiosk_mode, "pin-setup")),
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
        with transaction.atomic():
            admin_group, _editor_group, _huebers_group = bootstrap_default_roles()
            user = form.save()
            user.groups.add(admin_group)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Erster Admin-Benutzer wurde angelegt.")
        return redirect("camp-list")

    return render(request, "billing/setup.html", {"form": form})


def _is_application_admin_account(user: Any) -> bool:
    return user.is_superuser or user_role(user) == ROLE_ADMIN


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
        user_rows.append({"user": managed_user, "role": role, "phone": phone})
    return render(request, "billing/user_list.html", {"user_rows": user_rows})


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
    form = UserPasswordResetForm(managed_user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
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
            "cost_centers": cost_centers,
        },
    )


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

    if request.method == "POST" and request.POST.get("action") == "add_manual_charge":
        rule_id = request.POST.get("price_rule_id")
        quantity = int(request.POST.get("quantity", 1))
        description = request.POST.get("description", "").strip()

        rule = get_object_or_404(PriceRule, pk=rule_id, camp=participant.camp)

        charge = Charge.objects.create(
            participant=participant,
            price_rule=rule,
            description=description,
            unit_price=rule.unit_price,
            quantity=quantity,
            total_price=rule.unit_price * quantity,
            foerdersatz=rule.foerdersatz,
        )

        BookingAuditLog.objects.create(
            charge=charge,
            participant=participant,
            changed_by=request.user,
            action=BookingAuditLog.Action.CREATE,
            changes={"note": "Manuelle Buchung durch Admin"},
        )

        messages.success(request, f"Buchung '{rule.name}' hinzugefügt.")
        return redirect("participant-detail", participant_id=participant.pk)

    settlement = calculate_participant_settlement(participant)
    charges = participant.charges.filter(deleted_at__isnull=True).order_by("-created_at", "-id")
    audit_logs = BookingAuditLog.objects.filter(
        Q(participant=participant) | Q(charge__participant=participant)
    ).select_related("changed_by", "charge")
    settlement_snapshots = participant.settlements.filter(run__isnull=False).select_related("run", "run__camp")

    price_rules = participant.camp.price_rules.filter(is_archived=False).order_by("name")

    return render(
        request,
        "billing/participant_detail.html",
        {
            "participant": participant,
            "settlement": settlement,
            "charges": charges,
            "audit_logs": audit_logs,
            "settlement_snapshots": settlement_snapshots,
            "price_rules": price_rules,
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
        messages.success(request, "Teilnehmer-PIN wurde zurückgesetzt.")
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
        as_attachment=False,
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

        expense.allocation_method = allocation_method
        expense.cost_center = cost_center
        try:
            approve_shared_expense(expense, approved_by=request.user, participant_ids=participant_ids)
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


def kiosk_login(request, kiosk_mode="private"):
    """Authenticate a participant in a private or central kiosk session."""
    _activate_kiosk_mode(request, kiosk_mode)
    if request.session.get(KIOSK_PARTICIPANT_SESSION_KEY):
        if _kiosk_participant(request) is not None:
            return redirect(_kiosk_route(kiosk_mode, "home"))
        else:
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
    if request.method == "POST" and getattr(form, "missing_pin_family_member", None) is not None:
        request.session[KIOSK_PIN_SETUP_SESSION_KEY] = form.missing_pin_participant.pk
        request.session[KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY] = form.missing_pin_family_member.pk
        messages.info(
            request,
            "Für diesen Begleiter ist noch kein PIN gesetzt. Bitte lege jetzt einen neuen PIN fest.",
        )
        return redirect(_kiosk_route(kiosk_mode, "pin-setup"))
    if request.method == "POST" and getattr(form, "missing_pin_participant", None) is not None:
        request.session[KIOSK_PIN_SETUP_SESSION_KEY] = form.missing_pin_participant.pk
        request.session.pop(KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY, None)
        messages.info(
            request,
            "Für diesen Teilnehmer ist noch kein PIN gesetzt. Bitte lege jetzt einen neuen PIN fest.",
        )
        return redirect(_kiosk_route(kiosk_mode, "pin-setup"))

    return render(request, "billing/kiosk_login.html", {"form": form, **_kiosk_context(kiosk_mode)})


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
        Q(inviter=participant) | Q(invitee=participant),
        status=ParticipantBookingLink.Status.ACCEPTED,
        inviter__archived_at__isnull=True,
        invitee__archived_at__isnull=True,
    )


def _linked_booking_participants(participant):
    linked_participants = []
    for link in _accepted_booking_links(participant):
        linked_participants.append(link.invitee if link.inviter_id == participant.pk else link.inviter)
    return sorted(linked_participants, key=lambda item: (item.last_name, item.first_name, item.pk))


def _kiosk_checkin_participants(participant):
    targets = [
        {
            "token": f"participant-{participant.pk}",
            "object": participant,
            "name": participant.full_name,
            "role": "Ich",
            "camp": participant.camp,
        }
    ]
    for member in participant.family_members.filter(
        is_active=True,
        role=ParticipantFamilyMember.Role.COMPANION,
    ).order_by("last_name", "first_name"):
        targets.append(
            {
                "token": f"family-{member.pk}",
                "object": member,
                "name": member.full_name,
                "role": member.get_role_display(),
                "camp": participant.camp,
            }
        )
    for linked_participant in _linked_booking_participants(participant):
        targets.append(
            {
                "token": f"participant-{linked_participant.pk}",
                "object": linked_participant,
                "name": linked_participant.full_name,
                "role": "Verknüpft",
                "camp": linked_participant.camp,
            }
        )
    return targets


def _parse_kiosk_checkin_date(value, field_label, participant_name, errors):
    stripped_value = (value or "").strip()
    if not stripped_value:
        return None
    parsed = parse_date(stripped_value)
    if parsed is None:
        errors.append(f"{field_label} für {participant_name} ist kein gültiges Datum.")
    return parsed


def _validate_kiosk_checkin_dates(target, camp, arrival_date, departure_date, errors):
    if arrival_date and departure_date and departure_date <= arrival_date:
        errors.append(f"Die Abreise für {target.full_name} muss nach der Anreise liegen.")
    if camp.starts_on and arrival_date and arrival_date < camp.starts_on:
        errors.append(f"Die Anreise für {target.full_name} liegt vor Lagerbeginn.")
    if camp.ends_on and arrival_date and arrival_date > camp.ends_on:
        errors.append(f"Die Anreise für {target.full_name} liegt nach Lagerende.")
    if camp.starts_on and departure_date and departure_date < camp.starts_on:
        errors.append(f"Die Abreise für {target.full_name} liegt vor Lagerbeginn.")
    if camp.ends_on and departure_date and departure_date > camp.ends_on:
        errors.append(f"Die Abreise für {target.full_name} liegt nach Lagerende.")


def _update_kiosk_checkin_dates(request, participant, checkin_participants):
    targets_by_token = {target["token"]: target for target in checkin_participants}
    submitted_tokens = request.POST.getlist("checkin_target")
    updates = []
    errors = []

    for token in submitted_tokens:
        target = targets_by_token.get(token)
        if target is None:
            errors.append("Ein Teilnehmer darf über diesen Kiosk nicht bearbeitet werden.")
            continue
        target_object = target["object"]
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
        updates.append((target_object, arrival_date, departure_date))

    if errors:
        for error in errors:
            messages.error(request, error)
        return False

    with transaction.atomic():
        for target, arrival_date, departure_date in updates:
            target.arrival_date = arrival_date
            target.departure_date = departure_date
            update_fields = ["arrival_date", "departure_date", "updated_at"]
            if isinstance(target, Participant):
                target.booked_nights = (
                    max((departure_date - arrival_date).days, 0) if arrival_date and departure_date else 0
                )
                update_fields.append("booked_nights")
            target.save(update_fields=update_fields)
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


def _kiosk_meal_targets(participant):
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
    for member in participant.family_members.filter(is_active=True).order_by("last_name", "first_name"):
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
    for linked_participant in _linked_booking_participants(participant):
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
    return targets


def _target_lookup(meal_targets):
    return {target["token"]: target for target in meal_targets}


def _target_token_for_signup(signup):
    if signup.family_member_id is not None:
        return f"family-{signup.family_member_id}"
    return f"participant-{signup.participant_id}"


def _notify_linked_booking_by_id(charge_id: int, actor_id: int, *, cancelled: bool) -> None:
    charge = Charge.objects.select_related("participant", "kiosk_booked_by").get(pk=charge_id)
    actor = Participant.objects.get(pk=actor_id)
    notify_linked_booking(charge, actor=actor, cancelled=cancelled)


def _book_meal_for_target(target, meal_date, meal, variant, price_rule, booked_by):
    meal_display = dict(MealSignup.Meal.choices).get(meal, meal)
    target_object = target["object"]
    participant = target_object if target["kind"] == "participant" else target_object.guardian
    family_member = target_object if target["kind"] == "family" else None
    signup_defaults = {
        "variant": variant,
        "status": MealSignup.Status.ACTIVE,
        "foerdersatz": price_rule.foerdersatz,
        "retracted_at": None,
    }
    charge_description = f"{price_rule.name} {meal_display}"
    if family_member is not None:
        charge_description = f"{charge_description} für {family_member.full_name}"
    signup, _created = MealSignup.objects.update_or_create(
        participant=participant,
        family_member=family_member,
        meal_date=meal_date,
        meal=meal,
        defaults=signup_defaults,
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
    transaction.on_commit(partial(_notify_linked_booking_by_id, charge.pk, booked_by.pk, cancelled=False))


def _retract_meal_signup(signup: MealSignup, actor: Participant) -> None:
    signup.status = MealSignup.Status.RETRACTED
    signup.retracted_at = timezone.now()
    signup.save(update_fields=["status", "retracted_at", "updated_at"])
    charge = signup.charge
    if charge is None:
        return
    charge.deleted_at = timezone.now()
    charge.deleted_by = None
    charge.save(update_fields=["deleted_at", "deleted_by"])
    transaction.on_commit(partial(_notify_linked_booking_by_id, charge.pk, actor.pk, cancelled=True))


def _is_kiosk_quick_charge_cancelable(charge: Charge, participant: Participant, now=None) -> bool:
    """Return whether a kiosk participant may cancel a quick charge."""
    current_time = now or timezone.now()
    return (
        charge.deleted_at is None
        and charge.kiosk_booked_by_id is not None
        and charge.kind in {Charge.Kind.DRINK, Charge.Kind.FOOD}
        and charge.created_at >= current_time - KIOSK_QUICK_BOOKING_CANCEL_WINDOW
        and (charge.participant_id == participant.pk or charge.kiosk_booked_by_id == participant.pk)
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


def _kiosk_meal_calendar(camp, participant, meal_signups, meal_targets):
    signups_by_date_meal = {}
    included_dates = {signup.meal_date for signup in meal_signups}
    for signup in meal_signups:
        signups_by_date_meal.setdefault((signup.meal_date, signup.meal), []).append(signup)

    meal_dates = camp_meal_dates(camp, included_dates)
    menu_descriptions = {
        entry.meal_date: entry.description
        for entry in MealPlanEntry.objects.filter(camp=camp, meal=MealSignup.Meal.DINNER, meal_date__in=meal_dates)
    }
    meal_labels = dict(MealSignup.Meal.choices)
    days = []
    for meal_date in meal_dates:
        meals = []
        for meal, _label in [(MealSignup.Meal.DINNER, "Abendessen")]:
            scoped = signups_by_date_meal.get((meal_date, meal), [])
            active_signups = [signup for signup in scoped if signup.status == MealSignup.Status.ACTIVE]
            retracted_signups = [signup for signup in scoped if signup.status == MealSignup.Status.RETRACTED]
            locked = is_meal_change_locked(camp, meal_date)
            lock_message = meal_change_lock_message(camp, meal_date) if locked else ""
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
            meals.append(
                {
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
                }
            )
        dinner_slot = meals[0]
        days.append(
            {
                "date": meal_date,
                "status": dinner_slot["status"],
                "status_label": dinner_slot["status_label"],
                "locked": dinner_slot["locked"],
                "lock_message": dinner_slot["lock_message"],
                "price_rule": dinner_slot["price_rule"],
                "unit_price": dinner_slot["unit_price"],
                "description": dinner_slot["description"],
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


def kiosk_pin_setup(request, kiosk_mode="private"):
    """Create the initial PIN while retaining the kiosk device mode."""
    _activate_kiosk_mode(request, kiosk_mode)
    participant = _kiosk_participant_from_session(request, KIOSK_PIN_SETUP_SESSION_KEY)
    if participant is None:
        return redirect(_kiosk_route(kiosk_mode, "login"))
    family_member_id = request.session.get(KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY)
    family_member = None
    if family_member_id:
        family_member = (
            ParticipantFamilyMember.objects.select_related("guardian", "guardian__camp")
            .filter(
                pk=family_member_id,
                guardian=participant,
                role=ParticipantFamilyMember.Role.COMPANION,
                is_active=True,
            )
            .first()
        )
        if family_member is None:
            request.session.pop(KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY, None)
            return redirect(_kiosk_route(kiosk_mode, "login"))

    if family_member is not None:
        pin_holder = family_member
        pin_record, _created = ParticipantFamilyMemberPin.objects.get_or_create(family_member=family_member)
    else:
        pin_holder = participant
        pin_record, _created = ParticipantPin.objects.get_or_create(participant=participant)
    if not pin_record.must_set_pin and pin_record.pin_hash:
        return redirect(_kiosk_route(kiosk_mode, "home"))

    form = KioskPinSetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            pin_record.set_pin(form.cleaned_data["pin"])
            pin_record.save()
            request.session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
            if family_member is not None:
                request.session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = family_member.pk
            else:
                request.session.pop(KIOSK_FAMILY_MEMBER_SESSION_KEY, None)
            request.session.pop(KIOSK_PIN_SETUP_SESSION_KEY, None)
            request.session.pop(KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY, None)
            if kiosk_mode == "private":
                request.session.set_expiry(None)
        messages.success(request, "PIN wurde gesetzt. Du bist jetzt im Kiosk angemeldet.")
        return redirect(_kiosk_route(kiosk_mode, "home"))

    return render(
        request,
        "billing/kiosk_pin_setup.html",
        {"form": form, "participant": pin_holder, **_kiosk_context(kiosk_mode)},
    )


def kiosk_home(request, kiosk_mode="private"):
    """Render and process participant kiosk workflows for the selected device mode."""
    _activate_kiosk_mode(request, kiosk_mode)
    participant = _kiosk_participant(request)
    if participant is None:
        return redirect(_kiosk_route(kiosk_mode, "login"))

    active_family_member = _kiosk_family_member(request, participant)
    default_booking_target = active_family_member or participant
    default_booking_target_token = (
        f"family-{active_family_member.pk}" if active_family_member is not None else f"participant-{participant.pk}"
    )
    next_order_date = next_catering_order_date()
    next_meal_order = meal_order_for_date(participant.camp, next_order_date)
    meal_targets = _kiosk_meal_targets(participant)
    checkin_participants = _kiosk_checkin_participants(participant)
    quick_form = QuickBookingForm(participant=participant, prefix="quick")
    meal_form = MealBookingForm(participant=participant, prefix="meal")
    family_member_form = KioskFamilyMemberForm(prefix="family")
    booking_link_form = KioskBookingLinkInviteForm(inviter=participant, prefix="link")
    if request.method == "POST":
        if request.POST.get("action") == "quick":
            quick_form = QuickBookingForm(request.POST, participant=participant, prefix="quick")
            if quick_form.is_valid():
                target_ids = request.POST.getlist("quick-target")
                targets = [default_booking_target]
                if target_ids:
                    targets_by_token = _target_lookup(meal_targets)
                    selected_targets = [
                        targets_by_token[tid]["object"] for tid in target_ids if tid in targets_by_token
                    ]
                    if selected_targets:
                        targets = selected_targets

                rule = quick_form.cleaned_data["price_rule"]
                occurred_on = timezone.localdate()
                with transaction.atomic():
                    for target in set(targets):
                        if hasattr(target, "first_name") and hasattr(target, "last_name") and hasattr(target, "role"):
                            # This is a ParticipantFamilyMember
                            charge_participant = target.guardian
                            target_is_child = target.is_child
                            target_is_companion = target.role == target.Role.COMPANION
                        else:
                            charge_participant = target
                            target_is_child = target.is_child
                            target_is_companion = target.is_companion
                        effective_rule = rule
                        if rule.kind == PriceRule.Kind.MEAL:
                            resolved_rule = resolve_meal_price_rule(
                                participant.camp,
                                rule.meal_type,
                                occurred_on,
                                is_child=target_is_child,
                                is_companion=target_is_companion,
                            )
                            if resolved_rule is not None and resolved_rule.meal_date == occurred_on:
                                effective_rule = resolved_rule
                        charge_desc = f"{effective_rule.name} (Kiosk)"
                        if target != participant:
                            charge_desc = f"{effective_rule.name} (Kiosk) für {target.full_name}"

                        charge = Charge(
                            participant=charge_participant,
                            kind=Charge.Kind.DRINK if effective_rule.kind == PriceRule.Kind.DRINK else Charge.Kind.FOOD,
                            description=charge_desc,
                            quantity=quick_form.cleaned_data["quantity"],
                            unit_price=effective_rule.unit_price,
                            foerdersatz=effective_rule.foerdersatz,
                            occurred_on=occurred_on,
                            kiosk_booked_by=participant,
                        )
                        charge.save()
                        transaction.on_commit(
                            partial(_notify_linked_booking_by_id, charge.pk, participant.pk, cancelled=False)
                        )
                if not quick_form.errors:
                    messages.success(request, f"{rule.name} gebucht.")
                    return redirect(_kiosk_route(kiosk_mode, "home"))
        elif request.POST.get("action") == "quick_cancel":
            try:
                charge_id = int(request.POST.get("charge_id", ""))
            except ValueError:
                charge_id = None
            with transaction.atomic():
                charge = (
                    Charge.objects.select_for_update()
                    .filter(
                        Q(participant=participant) | Q(kiosk_booked_by=participant),
                        pk=charge_id,
                        kind__in=[Charge.Kind.DRINK, Charge.Kind.FOOD],
                        deleted_at__isnull=True,
                    )
                    .first()
                )
                if charge is None or not _is_kiosk_quick_charge_cancelable(charge, participant):
                    messages.error(request, "Diese Buchung kann nicht mehr storniert werden.")
                else:
                    charge.deleted_at = timezone.now()
                    charge.deleted_by = None
                    charge.save(update_fields=["deleted_at", "deleted_by"])
                    transaction.on_commit(
                        partial(_notify_linked_booking_by_id, charge.pk, participant.pk, cancelled=True)
                    )
                    messages.success(request, "Buchung wurde storniert.")
                    return redirect(_kiosk_route(kiosk_mode, "home"))
        elif request.POST.get("action") == "meal":
            meal_form = MealBookingForm(request.POST, participant=participant, prefix="meal")
            if meal_form.is_valid():
                meal_dates = meal_form.cleaned_data["meal_dates"]
                meal = meal_form.cleaned_data["meal"]
                for meal_date in meal_dates:
                    if is_meal_change_locked(participant.camp, meal_date):
                        meal_form.add_error(None, meal_change_lock_message(participant.camp, meal_date))
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
                        for target, meal_date, variant, price_rule in bookings:
                            _book_meal_for_target(target, meal_date, meal, variant, price_rule, participant)
                    day_label = "Tag" if len(meal_dates) == 1 else "Tage"
                    person_label = "Person" if len(selected_targets) == 1 else "Personen"
                    messages.success(
                        request,
                        f"Essensanmeldung wurde für {len(meal_dates)} {day_label} und "
                        f"{len(selected_targets)} {person_label} gespeichert.",
                    )
                    return redirect(f"{reverse(_kiosk_route(kiosk_mode, 'home'))}#meal-calendar")
        elif request.POST.get("action") == "meal_retract":
            signup_id = request.POST.get("meal_signup_id")
            targets_by_token = _target_lookup(meal_targets)
            signup = (
                MealSignup.objects.select_related("participant", "family_member", "charge")
                .filter(pk=signup_id, status=MealSignup.Status.ACTIVE)
                .first()
            )
            if signup is None or _target_token_for_signup(signup) not in targets_by_token:
                messages.error(request, "Essensanmeldung wurde nicht gefunden.")
            elif is_meal_change_locked(participant.camp, signup.meal_date):
                messages.error(request, meal_change_lock_message(participant.camp, signup.meal_date))
            else:
                with transaction.atomic():
                    _retract_meal_signup(signup, participant)
                messages.success(request, "Essensanmeldung wurde zurückgenommen.")
                return redirect(_kiosk_route(kiosk_mode, "home"))
        elif request.POST.get("action") == "family_member_create":
            family_member_form = KioskFamilyMemberForm(request.POST, prefix="family")
            if family_member_form.is_valid():
                with transaction.atomic():
                    family_member = family_member_form.save(commit=False)
                    family_member.guardian = participant
                    family_member.save()
                messages.success(request, "Familienmitglied wurde angelegt.")
                return redirect(_kiosk_route(kiosk_mode, "home"))
        elif request.POST.get("action") == "family_member_deactivate":
            member_id = request.POST.get("family_member_id")
            family_member = participant.family_members.filter(pk=member_id, is_active=True).first()
            if family_member is not None:
                family_member.is_active = False
                family_member.save(update_fields=["is_active", "updated_at"])
                messages.success(request, "Familienmitglied wurde entfernt.")
                return redirect(_kiosk_route(kiosk_mode, "home"))
            messages.error(request, "Familienmitglied wurde nicht gefunden.")
        elif request.POST.get("action") == "booking_link_invite":
            booking_link_form = KioskBookingLinkInviteForm(request.POST, inviter=participant, prefix="link")
            if booking_link_form.is_valid():
                with transaction.atomic():
                    booking_link = ParticipantBookingLink.objects.create(
                        inviter=participant,
                        invitee=booking_link_form.cleaned_data["participant"],
                    )
                    transaction.on_commit(
                        lambda link_id=booking_link.pk, actor_id=participant.pk: notify_booking_link(
                            ParticipantBookingLink.objects.select_related("inviter", "invitee").get(pk=link_id),
                            event="invited",
                            actor=Participant.objects.get(pk=actor_id),
                        )
                    )
                messages.success(request, "Einladung wurde gesendet.")
                return redirect(_kiosk_route(kiosk_mode, "home"))
        elif request.POST.get("action") in ["booking_link_accept", "booking_link_decline", "booking_link_revoke"]:
            link_id = request.POST.get("booking_link_id")
            if request.POST.get("action") == "booking_link_accept":
                booking_link = participant.received_booking_links.filter(
                    pk=link_id,
                    status=ParticipantBookingLink.Status.PENDING,
                ).first()
                new_status = ParticipantBookingLink.Status.ACCEPTED
                success_message = "Einladung wurde angenommen."
            elif request.POST.get("action") == "booking_link_decline":
                booking_link = participant.received_booking_links.filter(
                    pk=link_id,
                    status=ParticipantBookingLink.Status.PENDING,
                ).first()
                new_status = ParticipantBookingLink.Status.DECLINED
                success_message = "Einladung wurde abgelehnt."
            else:
                booking_link = ParticipantBookingLink.objects.filter(
                    Q(inviter=participant) | Q(invitee=participant),
                    pk=link_id,
                    status=ParticipantBookingLink.Status.ACCEPTED,
                ).first()
                new_status = ParticipantBookingLink.Status.REVOKED
                success_message = "Verknüpfung wurde aufgelöst."
            if booking_link is not None:
                booking_link.status = new_status
                booking_link.save(update_fields=["status", "updated_at"])
                event = {
                    ParticipantBookingLink.Status.ACCEPTED: "accepted",
                    ParticipantBookingLink.Status.DECLINED: "declined",
                    ParticipantBookingLink.Status.REVOKED: "revoked",
                }[new_status]
                transaction.on_commit(
                    lambda link_id=booking_link.pk, actor_id=participant.pk, event_name=event: notify_booking_link(
                        ParticipantBookingLink.objects.select_related("inviter", "invitee").get(pk=link_id),
                        event=event_name,
                        actor=Participant.objects.get(pk=actor_id),
                    )
                )
                messages.success(request, success_message)
                return redirect(_kiosk_route(kiosk_mode, "home"))
            messages.error(request, "Verknüpfung wurde nicht gefunden.")
        elif request.POST.get("action") == "checkin":
            if _update_kiosk_checkin_dates(request, participant, checkin_participants):
                return redirect(_kiosk_route(kiosk_mode, "home"))

    recent_quick_charges = list(
        Charge.objects.select_related("participant", "kiosk_booked_by")
        .filter(
            Q(participant=participant) | Q(kiosk_booked_by=participant),
            kind__in=[Charge.Kind.DRINK, Charge.Kind.FOOD],
            deleted_at__isnull=True,
            kiosk_booked_by__isnull=False,
        )
        .distinct()
        .order_by("-created_at")[:8]
    )
    quick_cancel_now = timezone.now()
    for charge in recent_quick_charges:
        charge.is_kiosk_cancelable = _is_kiosk_quick_charge_cancelable(charge, participant, quick_cancel_now)
    linked_participant_ids = [
        target["object"].pk
        for target in meal_targets
        if target["kind"] == "participant" and target["object"].pk != participant.pk
    ]
    meal_signups = (
        MealSignup.objects.select_related("participant", "family_member")
        .filter(Q(participant=participant) | Q(participant_id__in=linked_participant_ids, family_member__isnull=True))
        .order_by("meal_date", "meal", "participant__last_name", "participant__first_name")
    )
    meal_signups = list(meal_signups)
    meal_calendar_days = _kiosk_meal_calendar(participant.camp, participant, meal_signups, meal_targets)
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
        status=ParticipantBookingLink.Status.PENDING
    )
    sent_invites = participant.sent_booking_links.select_related("invitee").filter(
        status=ParticipantBookingLink.Status.PENDING
    )
    accepted_links = _accepted_booking_links(participant)
    context = {
        "participant": participant,
        "kiosk_actor": default_booking_target,
        "kiosk_actor_is_family_member": active_family_member is not None,
        "default_booking_target_token": default_booking_target_token,
        "summary": participant_kiosk_summary(participant),
        "meal_form": meal_form,
        "meal_default_variant": meal_form.fields["variant"].choices[0][0],
        "family_member_form": family_member_form,
        "booking_link_form": booking_link_form,
        "recent_quick_charges": recent_quick_charges,
        "meal_signups": meal_signups,
        "meal_calendar_days": meal_calendar_days,
        "meal_calendar_groups": _group_kiosk_meal_calendar(meal_calendar_days),
        "meal_dialog_open": is_meal_post and bool(meal_form.errors),
        "meal_dialog_step": "persons" if selected_meal_date_values else "dates",
        "drink_rules": quick_form.fields["price_rule"].queryset.filter(kind=PriceRule.Kind.DRINK),
        "snack_rules": quick_form.fields["price_rule"].queryset.filter(kind=PriceRule.Kind.MEAL),
        "dinner_rule": dinner_rule,
        "quick_form": quick_form,
        "meal_targets": meal_targets,
        "checkin_participants": checkin_participants,
        "family_members": participant.family_members.filter(is_active=True).order_by("last_name", "first_name"),
        "pending_invites": pending_invites,
        "sent_invites": sent_invites,
        "accepted_links": accepted_links,
        **_kiosk_context(kiosk_mode),
        "kiosk_contacts": admin_interface_contacts(User),
        "next_order_date": next_order_date,
        "next_meal_order": next_meal_order,
        "next_order_locked": is_meal_change_locked(participant.camp, next_order_date),
        "today": today,
        "tomorrow": tomorrow,
        "participant_expenses": participant.expenses.all().order_by("-created_at"),
    }
    return render(request, "billing/kiosk_home.html", context)


def kiosk_shared_expense_request(request, kiosk_mode="private"):
    """Create a shared-expense request from the selected kiosk mode."""
    _activate_kiosk_mode(request, kiosk_mode)
    participant = _kiosk_participant(request)
    if not participant:
        return redirect(_kiosk_route(kiosk_mode, "login"))

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

    today = timezone.localdate()
    if request.method == "POST":
        action = request.POST.get("action")
        shift_id = request.POST.get("shift_id")
        shift = get_object_or_404(Shift, pk=shift_id, camp=participant.camp)

        if action == "signup":
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
                    offered_assignment.save(update_fields=["participant", "offered_for_exchange"])
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
            messages.error(
                request,
                "Das direkte Austragen aus Diensten ist nicht mehr möglich. Bitte biete deinen Dienst zum Tausch an "
                "oder wende dich an die Lagerleitung.",
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

        return redirect(_kiosk_route(kiosk_mode, "shifts"))

    shifts = (
        participant.camp.shifts.filter(date__gte=today)
        .prefetch_related("assignments__participant")
        .order_by("date", "start_time")
    )
    open_shifts = []
    offered_shifts = []
    my_shifts = []

    for shift in shifts:
        shift_assignments = list(shift.assignments.all())
        shift.my_assignment = next((a for a in shift_assignments if a.participant_id == participant.pk), None)
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

    return render(
        request,
        "billing/kiosk_shifts.html",
        {
            "participant": participant,
            "open_shifts": open_shifts,
            "offered_shifts": offered_shifts,
            "my_shifts": my_shifts,
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
