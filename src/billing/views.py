import base64
import json

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature, Signer
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from .exporters import (
    camp_settlement_csv,
    camp_workbook_response,
    drink_entries_csv,
    participant_pdf_response,
    settlement_run_csv,
)
from .forms import (
    CampForm,
    ChargeForm,
    DrinkBookingForm,
    ExpenseForm,
    FirstAdminSetupForm,
    KioskLinkedParticipantForm,
    KioskLoginForm,
    KioskPinSetupForm,
    KioskStayForm,
    MealBookingForm,
    OvernightCategoryForm,
    ParticipantForm,
    ParticipantImportForm,
    ParticipantPinForm,
    PaymentForm,
    PriceRuleForm,
)
from .importers import preview_participants, rows_from_payload, rows_to_payload, save_participants
from .models import Camp, Charge, MealSignup, OvernightCategory, Participant, PriceRule, SettlementRun
from .permissions import admin_required, editor_required
from .roles import bootstrap_default_roles
from .services import (
    calculate_camp_settlements,
    calculate_participant_settlement,
    create_settlement_run,
    participant_kiosk_summary,
)

signer = Signer()
User = get_user_model()
KIOSK_PARTICIPANT_SESSION_KEY = "kiosk_participant_id"
KIOSK_PIN_SETUP_SESSION_KEY = "kiosk_pin_setup_participant_id"
PRICE_RULE_SECTION_IDS = {
    PriceRule.Kind.CAMP_FLAT: "prices-camp-flat",
    PriceRule.Kind.DRINK: "prices-drinks",
    PriceRule.Kind.MEAL: "prices-meals",
    PriceRule.Kind.NIGHT: "prices-other",
    PriceRule.Kind.OTHER: "prices-other",
}


class FirstLaunchLoginView(LoginView):
    def dispatch(self, request, *args, **kwargs):
        if not User.objects.exists():
            return redirect("setup")
        return super().dispatch(request, *args, **kwargs)


def _price_rule_is_overlay(request):
    return request.GET.get("overlay") == "1" or request.POST.get("overlay") == "1"


def _price_rule_kind_from_request(request):
    requested_kind = request.GET.get("kind") or request.POST.get("kind") or ""
    if not requested_kind:
        return ""
    valid_kinds = {choice for choice, _label in PriceRule.Kind.choices}
    if requested_kind not in valid_kinds:
        return None
    return requested_kind


def _price_rule_grouped_rules(camp):
    return {
        "camp_flat": camp.price_rules.filter(kind=PriceRule.Kind.CAMP_FLAT).select_related("overnight_category"),
        "drinks": camp.price_rules.filter(kind=PriceRule.Kind.DRINK).select_related("overnight_category"),
        "meals": camp.price_rules.filter(kind=PriceRule.Kind.MEAL).select_related("overnight_category"),
        "other": camp.price_rules.filter(kind__in=[PriceRule.Kind.NIGHT, PriceRule.Kind.OTHER]).select_related(
            "overnight_category"
        ),
    }


def _price_rule_manage_context(camp):
    return {
        "camp": camp,
        "grouped_rules": _price_rule_grouped_rules(camp),
        "overnight_categories": camp.overnight_categories.order_by("name"),
    }


def _price_rule_manage_url(camp, kind):
    url = reverse("price-rules-manage", kwargs={"camp_id": camp.pk})
    section_id = PRICE_RULE_SECTION_IDS.get(kind)
    return f"{url}#{section_id}" if section_id else url


def _render_price_rule_form(request, *, camp, form, title, submit_label, cancel_url, overlay_mode):
    context = {
        "camp": camp,
        "form": form,
        "title": title,
        "submit_label": submit_label,
        "cancel_url": cancel_url,
        "form_action": request.get_full_path(),
        "overlay_mode": overlay_mode,
    }
    template_name = "billing/price_rule_dialog.html" if overlay_mode else "billing/price_rule_form.html"
    return render(request, template_name, context)


def _price_rule_overlay_success_response(request, *, camp, kind, message):
    sections_html = render_to_string(
        "billing/price_rule_sections.html",
        _price_rule_manage_context(camp),
        request=request,
    )
    return JsonResponse(
        {
            "success": True,
            "message": message,
            "sections_html": sections_html,
            "section_id": PRICE_RULE_SECTION_IDS.get(kind, ""),
        }
    )


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


@admin_required
def camp_delete(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    if request.method == "POST":
        camp_name = str(camp)
        with transaction.atomic():
            camp.participants.all().delete()
            camp.price_rules.all().delete()
            camp.overnight_categories.all().delete()
            camp.delete()
        messages.success(request, f"{camp_name} wurde gelöscht.")
        return redirect("camp-list")
    return render(
        request,
        "billing/confirm_delete.html",
        {
            "title": "Lager löschen",
            "object_name": str(camp),
            "cancel_url": reverse("camp-detail", kwargs={"camp_id": camp.pk}),
            "warning": (
                "Teilnehmer, Preise, Auslagen, Abrechnungsläufe und alle weiteren "
                "Lagerdaten werden dauerhaft entfernt."
            ),
        },
    )


@editor_required
def camp_detail(request, camp_id):
    camp = get_object_or_404(Camp.objects.prefetch_related("overnight_categories"), pk=camp_id)
    settlements = calculate_camp_settlements(camp)
    totals = {
        "gross": sum(result.total_gross for result in settlements),
        "subsidy": sum(result.total_subsidy for result in settlements),
        "due": sum(result.total_due for result in settlements),
        "paid": sum(result.total_paid for result in settlements),
        "advanced": sum(result.total_advanced for result in settlements),
        "balance": sum(result.balance for result in settlements),
    }
    price_rules = camp.price_rules.select_related("overnight_category")
    settlement_runs = camp.settlement_runs.select_related("created_by")[:5]
    return render(
        request,
        "billing/camp_detail.html",
        {
            "camp": camp,
            "settlements": settlements,
            "totals": totals,
            "price_rules": price_rules,
            "overnight_categories": camp.overnight_categories.order_by("name"),
            "settlement_runs": settlement_runs,
        },
    )


@editor_required
def settlement_run_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    if request.method != "POST":
        return redirect("camp-detail", camp_id=camp.pk)
    run = create_settlement_run(camp, request.user)
    messages.success(request, "Abrechnungslauf wurde gespeichert.")
    return redirect("settlement-run-detail", run_id=run.pk)


@editor_required
def settlement_run_detail(request, run_id):
    run = get_object_or_404(SettlementRun.objects.select_related("camp", "created_by"), pk=run_id)
    settlements = run.settlements.select_related("participant").order_by(
        "participant__last_name",
        "participant__first_name",
    )
    return render(request, "billing/settlement_run_detail.html", {"run": run, "settlements": settlements})


@editor_required
def participant_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = ParticipantForm(request.POST or None, camp=camp)
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
    participant = get_object_or_404(
        Participant.objects.select_related("camp", "overnight_category", "primary_participant").prefetch_related(
            "linked_participants__overnight_category"
        ),
        pk=participant_id,
    )
    settlement = calculate_participant_settlement(participant)
    return render(request, "billing/participant_detail.html", {"participant": participant, "settlement": settlement})


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
    requested_kind = _price_rule_kind_from_request(request)
    overlay_mode = _price_rule_is_overlay(request)
    if requested_kind is None:
        return HttpResponseBadRequest("Ungültige Preisart.")

    form = PriceRuleForm(request.POST or None, fixed_kind=requested_kind or None, camp=camp)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            rule = form.save(commit=False)
            rule.camp = camp
            rule.save()
        success_message = "Preisregel wurde gespeichert."
        if overlay_mode:
            return _price_rule_overlay_success_response(
                request,
                camp=camp,
                kind=rule.kind,
                message=success_message,
            )
        messages.success(request, success_message)
        return redirect(_price_rule_manage_url(camp, rule.kind))
    return _render_price_rule_form(
        request,
        camp=camp,
        form=form,
        title=f"{form.category_label} anlegen",
        submit_label="Preis speichern",
        cancel_url=reverse("price-rules-manage", kwargs={"camp_id": camp.pk}),
        overlay_mode=overlay_mode,
    )


@admin_required
def price_rules_manage(request, camp_id):
    camp = get_object_or_404(Camp.objects.prefetch_related("overnight_categories"), pk=camp_id)
    return render(request, "billing/price_rules_manage.html", _price_rule_manage_context(camp))


@admin_required
def price_rule_edit(request, price_rule_id):
    rule = get_object_or_404(PriceRule.objects.select_related("camp"), pk=price_rule_id)
    overlay_mode = _price_rule_is_overlay(request)
    form = PriceRuleForm(request.POST or None, instance=rule, fixed_kind=rule.kind, camp=rule.camp)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
        success_message = "Preisregel wurde gespeichert."
        if overlay_mode:
            return _price_rule_overlay_success_response(
                request,
                camp=rule.camp,
                kind=rule.kind,
                message=success_message,
            )
        messages.success(request, success_message)
        return redirect(_price_rule_manage_url(rule.camp, rule.kind))
    return _render_price_rule_form(
        request,
        camp=rule.camp,
        form=form,
        title=f"{form.category_label} bearbeiten",
        submit_label="Änderungen speichern",
        cancel_url=reverse("price-rules-manage", kwargs={"camp_id": rule.camp.pk}),
        overlay_mode=overlay_mode,
    )


@admin_required
def overnight_category_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = OvernightCategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            category = form.save(commit=False)
            category.camp = camp
            category.save()
        messages.success(request, "Uebernachtungskategorie wurde gespeichert.")
        return redirect("price-rules-manage", camp_id=camp.pk)
    return render(
        request,
        "billing/form.html",
        {"form": form, "title": "Uebernachtungskategorie anlegen", "camp": camp},
    )


@admin_required
def overnight_category_edit(request, category_id):
    category = get_object_or_404(OvernightCategory.objects.select_related("camp"), pk=category_id)
    form = OvernightCategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
        messages.success(request, "Uebernachtungskategorie wurde gespeichert.")
        return redirect("price-rules-manage", camp_id=category.camp.pk)
    return render(
        request,
        "billing/form.html",
        {"form": form, "title": "Uebernachtungskategorie bearbeiten", "camp": category.camp},
    )


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
def export_settlement_run_csv(request, run_id):
    return settlement_run_csv(get_object_or_404(SettlementRun.objects.select_related("camp"), pk=run_id))


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
        Participant.objects.select_related("camp", "overnight_category", "primary_participant")
        .prefetch_related("linked_participants__overnight_category")
        .filter(pk=participant_id, camp__is_active=True)
        .first()
    )


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

    drink_form = DrinkBookingForm(camp=participant.camp, prefix="drink")
    meal_form = MealBookingForm(camp=participant.camp, prefix="meal")
    stay_form = KioskStayForm(instance=participant, camp=participant.camp, prefix="stay")
    linked_form = KioskLinkedParticipantForm(camp=participant.camp, prefix="linked")
    if request.method == "POST":
        if request.POST.get("action") == "drink":
            drink_form = DrinkBookingForm(request.POST, camp=participant.camp, prefix="drink")
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
            meal_form = MealBookingForm(request.POST, camp=participant.camp, prefix="meal")
            if meal_form.is_valid():
                price_rule = meal_form.cleaned_data["price_rule"]
                meal_display = dict(MealSignup.Meal.choices).get(
                    meal_form.cleaned_data["meal"],
                    meal_form.cleaned_data["meal"],
                )
                with transaction.atomic():
                    MealSignup.objects.update_or_create(
                        participant=participant,
                        meal_date=meal_form.cleaned_data["meal_date"],
                        meal=meal_form.cleaned_data["meal"],
                        defaults={
                            "variant": meal_form.cleaned_data["variant"],
                            "foerderfaehig": price_rule.foerderfaehig,
                        },
                    )
                    Charge.objects.update_or_create(
                        participant=participant,
                        kind=Charge.Kind.FOOD,
                        occurred_on=meal_form.cleaned_data["meal_date"],
                        description=f"{price_rule.name} {meal_display}",
                        defaults={
                            "quantity": 1,
                            "unit_price": price_rule.unit_price,
                            "foerderfaehig": price_rule.foerderfaehig,
                        },
                    )
                messages.success(request, "Essensanmeldung wurde gespeichert.")
                return redirect("kiosk-home")
        elif request.POST.get("action") == "stay":
            stay_form = KioskStayForm(request.POST, instance=participant, camp=participant.camp, prefix="stay")
            if stay_form.is_valid():
                with transaction.atomic():
                    stay_form.save()
                messages.success(request, "Dein Aufenthalt wurde aktualisiert.")
                return redirect("kiosk-home")
        elif request.POST.get("action") == "linked-participant":
            linked_form = KioskLinkedParticipantForm(request.POST, camp=participant.camp, prefix="linked")
            if linked_form.is_valid():
                with transaction.atomic():
                    linked_participant = linked_form.save(commit=False)
                    linked_participant.camp = participant.camp
                    linked_participant.primary_participant = participant
                    linked_participant.status = Participant.Status.REGISTERED
                    linked_participant.is_youth_group = participant.is_youth_group
                    linked_participant.hilfssatz = participant.hilfssatz
                    linked_participant.berufssatz = participant.berufssatz
                    linked_participant.save()
                messages.success(request, "Zusatzperson wurde angelegt.")
                return redirect("kiosk-home")

    recent_drinks = participant.charges.filter(kind=Charge.Kind.DRINK).order_by("-created_at")[:8]
    meal_signups = participant.meal_signups.order_by("meal_date", "meal")
    context = {
        "participant": participant,
        "summary": participant_kiosk_summary(participant),
        "drink_form": drink_form,
        "meal_form": meal_form,
        "stay_form": stay_form,
        "linked_form": linked_form,
        "linked_participants": participant.linked_participants.select_related("overnight_category").order_by(
            "last_name",
            "first_name",
        ),
        "recent_drinks": recent_drinks,
        "meal_signups": meal_signups,
        "drink_rules": PriceRule.objects.filter(camp=participant.camp, kind=PriceRule.Kind.DRINK).order_by("name"),
        "meal_rules": PriceRule.objects.filter(camp=participant.camp, kind=PriceRule.Kind.MEAL).order_by("name"),
        "kiosk_autologout": True,
    }
    return render(request, "billing/kiosk_home.html", context)
