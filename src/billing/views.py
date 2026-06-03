import base64
import json
from typing import Any

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature, Signer
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .exporters import camp_settlement_csv, camp_workbook_response, drink_entries_csv, participant_pdf_response
from .forms import (
    CampFlatRateSettingsForm,
    CampForm,
    ChargeForm,
    DrinkBookingForm,
    ExpenseForm,
    FirstAdminSetupForm,
    KioskLoginForm,
    KioskPinSetupForm,
    MealBookingForm,
    MealStandardPricesForm,
    ParticipantForm,
    ParticipantImportForm,
    ParticipantPinForm,
    PaymentForm,
    PriceRuleForm,
    UserCreateForm,
    UserEditForm,
    UserPasswordResetForm,
)
from .importers import preview_participants, rows_from_payload, rows_to_payload, save_participants
from .models import BookingAuditLog, Camp, Charge, MealSignup, Participant, PriceRule
from .permissions import ADMIN_GROUP, admin_required, editor_required
from .roles import ROLE_ADMIN, ROLE_EDITOR, active_admin_count, bootstrap_default_roles, set_user_role, user_role
from .services import (
    calculate_camp_settlements,
    calculate_participant_settlement,
    charge_audit_snapshot,
    create_booking_audit_log,
    create_booking_delete_audit_log,
    participant_kiosk_summary,
    restore_booking_from_audit_log,
)

signer = Signer()
User = get_user_model()
KIOSK_PARTICIPANT_SESSION_KEY = "kiosk_participant_id"
KIOSK_PIN_SETUP_SESSION_KEY = "kiosk_pin_setup_participant_id"


class FirstLaunchLoginView(LoginView):
    def dispatch(self, request, *args, **kwargs):
        if not User.objects.exists():
            return redirect("setup")
        return super().dispatch(request, *args, **kwargs)


def setup_first_admin(request):
    if User.objects.exists():
        return redirect("camp-list" if request.user.is_authenticated else "login")

    form = FirstAdminSetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            admin_group, _ = bootstrap_default_roles()
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
    users = User.objects.prefetch_related("groups").order_by("username")
    user_rows = []
    for managed_user in users:
        group_names = {group.name for group in managed_user.groups.all()}
        role = ROLE_ADMIN if managed_user.is_superuser or ADMIN_GROUP in group_names else ROLE_EDITOR
        user_rows.append({"user": managed_user, "role": role})
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
    totals = {
        "gross": sum(result.total_gross for result in settlements),
        "subsidy": sum(result.total_subsidy for result in settlements),
        "due": sum(result.total_due for result in settlements),
        "paid": sum(result.total_paid for result in settlements),
        "advanced": sum(result.total_advanced for result in settlements),
        "balance": sum(result.balance for result in settlements),
    }
    price_rules = camp.price_rules.all()
    return render(
        request,
        "billing/camp_detail.html",
        {"camp": camp, "settlements": settlements, "totals": totals, "price_rules": price_rules},
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
def participant_detail(request, participant_id):
    participant = get_object_or_404(Participant.objects.select_related("camp"), pk=participant_id)
    settlement = calculate_participant_settlement(participant)
    charges = participant.charges.filter(deleted_at__isnull=True).order_by("-created_at", "-id")
    audit_logs = BookingAuditLog.objects.filter(
        Q(participant=participant) | Q(charge__participant=participant)
    ).select_related("changed_by", "charge")
    return render(
        request,
        "billing/participant_detail.html",
        {
            "participant": participant,
            "settlement": settlement,
            "charges": charges,
            "audit_logs": audit_logs,
        },
    )


@editor_required
def charge_create(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id)
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
        charge.deleted_by = request.user
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
    participant = get_object_or_404(Participant, pk=participant_id)
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
    participant = get_object_or_404(Participant, pk=participant_id)
    if request.method == "POST":
        with transaction.atomic():
            participant.pin.reset_pin(changed_by=request.user)
            participant.pin.save()
        messages.success(request, "Teilnehmer-PIN wurde zurückgesetzt.")
    return redirect("participant-detail", participant_id=participant.pk)


@admin_required
def pin_set(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id)
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
        "drinks": camp.price_rules.filter(kind=PriceRule.Kind.DRINK),
        "meals": camp.price_rules.filter(kind=PriceRule.Kind.MEAL, is_default=False),
        "other": camp.price_rules.filter(kind__in=[PriceRule.Kind.NIGHT, PriceRule.Kind.OTHER]),
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


@editor_required
def expense_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = ExpenseForm(request.POST or None)
    form.fields["participant"].queryset = Participant.objects.filter(camp=camp)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            expense = form.save(commit=False)
            expense.camp = camp
            expense.save()
        messages.success(request, "Auslage wurde gespeichert.")
        return redirect("camp-detail", camp_id=camp.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Auslage erfassen"})


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
        save_participants(camp, valid_rows)
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
            payload = json.dumps(rows_to_payload(rows), ensure_ascii=False).encode("utf-8")
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
    return Participant.objects.select_related("camp").filter(pk=participant_id, camp__is_active=True).first()


def kiosk_login(request):
    if request.session.get(KIOSK_PARTICIPANT_SESSION_KEY):
        return redirect("kiosk-home")

    form = KioskLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.session[KIOSK_PARTICIPANT_SESSION_KEY] = form.cleaned_data["participant"].pk
        messages.success(request, "Du bist im Kiosk angemeldet.")
        return redirect("kiosk-home")
    if request.method == "POST" and getattr(form, "missing_pin_participant", None) is not None:
        request.session[KIOSK_PIN_SETUP_SESSION_KEY] = form.missing_pin_participant.pk
        messages.info(
            request,
            "Für diesen Teilnehmer ist noch kein PIN gesetzt. Bitte lege jetzt einen neuen PIN fest.",
        )
        return redirect("kiosk-pin-setup")

    return render(request, "billing/kiosk_login.html", {"form": form})


def kiosk_logout(request):
    request.session.pop(KIOSK_PARTICIPANT_SESSION_KEY, None)
    request.session.pop(KIOSK_PIN_SETUP_SESSION_KEY, None)
    messages.success(request, "Du wurdest vom Kiosk abgemeldet.")
    return redirect("kiosk-login")


def _kiosk_participant(request):
    return _kiosk_participant_from_session(request, KIOSK_PARTICIPANT_SESSION_KEY)


def kiosk_pin_setup(request):
    participant = _kiosk_participant_from_session(request, KIOSK_PIN_SETUP_SESSION_KEY)
    if participant is None:
        return redirect("kiosk-login")
    if not participant.pin.must_set_pin and participant.pin.pin_hash:
        return redirect("kiosk-home")

    form = KioskPinSetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            participant.pin.set_pin(form.cleaned_data["pin"])
            participant.pin.save()
            request.session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
            request.session.pop(KIOSK_PIN_SETUP_SESSION_KEY, None)
        messages.success(request, "PIN wurde gesetzt. Du bist jetzt im Kiosk angemeldet.")
        return redirect("kiosk-home")

    return render(
        request,
        "billing/kiosk_pin_setup.html",
        {"form": form, "participant": participant, "kiosk_autologout": True},
    )


def kiosk_home(request):
    participant = _kiosk_participant(request)
    if participant is None:
        return redirect("kiosk-login")

    drink_form = DrinkBookingForm(participant=participant, prefix="drink")
    meal_form = MealBookingForm(participant=participant, prefix="meal")
    if request.method == "POST":
        if request.POST.get("action") == "drink":
            drink_form = DrinkBookingForm(request.POST, participant=participant, prefix="drink")
            if drink_form.is_valid():
                price_rule = drink_form.cleaned_data["price_rule"]
                with transaction.atomic():
                    Charge.objects.create(
                        participant=participant,
                        kind=Charge.Kind.DRINK,
                        description=price_rule.name,
                        quantity=drink_form.cleaned_data["quantity"],
                        unit_price=price_rule.unit_price,
                        foerderfaehig=price_rule.foerderfaehig,
                    )
                messages.success(request, "Getränk wurde gebucht.")
                return redirect("kiosk-home")
        elif request.POST.get("action") == "meal":
            meal_form = MealBookingForm(request.POST, participant=participant, prefix="meal")
            if meal_form.is_valid():
                meal_date = meal_form.cleaned_data["meal_date"]
                meal = meal_form.cleaned_data["meal"]
                variant = meal_form.cleaned_data["variant"]

                is_child = variant in [MealSignup.Variant.NORMAL_CHILD, MealSignup.Variant.VEGAN_CHILD]

                price_rule = PriceRule.objects.filter(
                    camp=participant.camp,
                    kind=PriceRule.Kind.MEAL,
                    meal_type=meal,
                    applies_to_children=is_child,
                    meal_date=meal_date,
                ).first()

                if not price_rule:
                    price_rule = PriceRule.objects.filter(
                        camp=participant.camp,
                        kind=PriceRule.Kind.MEAL,
                        meal_type=meal,
                        applies_to_children=is_child,
                        is_default=True,
                        meal_date__isnull=True,
                    ).first()

                if not price_rule:
                    meal_form.add_error(
                        None, "Für diese Mahlzeit ist kein Preis hinterlegt. Bitte wende dich an die Lagerleitung."
                    )
                else:
                    meal_display = dict(MealSignup.Meal.choices).get(meal, meal)
                    with transaction.atomic():
                        MealSignup.objects.update_or_create(
                            participant=participant,
                            meal_date=meal_date,
                            meal=meal,
                            defaults={
                                "variant": variant,
                                "foerderfaehig": price_rule.foerderfaehig,
                            },
                        )
                        Charge.objects.update_or_create(
                            participant=participant,
                            kind=Charge.Kind.FOOD,
                            occurred_on=meal_date,
                            description=f"{price_rule.name} {meal_display}",
                            defaults={
                                "quantity": 1,
                                "unit_price": price_rule.unit_price,
                                "foerderfaehig": price_rule.foerderfaehig,
                            },
                        )
                    messages.success(request, "Essensanmeldung wurde gespeichert.")
                    return redirect("kiosk-home")

    recent_drinks = participant.charges.filter(kind=Charge.Kind.DRINK, deleted_at__isnull=True).order_by("-created_at")[
        :8
    ]
    meal_signups = participant.meal_signups.order_by("meal_date", "meal")
    context = {
        "participant": participant,
        "summary": participant_kiosk_summary(participant),
        "drink_form": drink_form,
        "meal_form": meal_form,
        "recent_drinks": recent_drinks,
        "meal_signups": meal_signups,
        "drink_rules": drink_form.fields["price_rule"].queryset,
        "kiosk_autologout": True,
    }
    return render(request, "billing/kiosk_home.html", context)
