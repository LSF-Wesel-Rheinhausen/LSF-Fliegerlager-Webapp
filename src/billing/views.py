import base64
import json

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.signing import BadSignature, Signer
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .exporters import camp_settlement_csv, camp_workbook_response, drink_entries_csv, participant_pdf_response
from .forms import (
    CampForm,
    ChargeForm,
    ExpenseForm,
    FirstAdminSetupForm,
    ParticipantForm,
    ParticipantImportForm,
    PaymentForm,
    PriceRuleForm,
)
from .importers import preview_participants, rows_from_payload, rows_to_payload, save_participants
from .models import Camp, Participant
from .permissions import admin_required, editor_required
from .roles import bootstrap_default_roles
from .services import calculate_camp_settlements, calculate_participant_settlement


signer = Signer()
User = get_user_model()


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


@editor_required
def camp_detail(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    settlements = calculate_camp_settlements(camp)
    totals = {
        "due": sum(result.total_due for result in settlements),
        "paid": sum(result.total_paid for result in settlements),
        "advanced": sum(result.total_advanced for result in settlements),
        "balance": sum(result.balance for result in settlements),
    }
    return render(request, "billing/camp_detail.html", {"camp": camp, "settlements": settlements, "totals": totals})


@editor_required
def participant_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = ParticipantForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
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
    return render(request, "billing/participant_detail.html", {"participant": participant, "settlement": settlement})


@editor_required
def charge_create(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id)
    form = ChargeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
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
        participant.pin.reset_pin(changed_by=request.user)
        participant.pin.save()
        messages.success(request, "Teilnehmer-PIN wurde zurückgesetzt.")
    return redirect("participant-detail", participant_id=participant.pk)


@admin_required
def price_rule_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = PriceRuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        rule = form.save(commit=False)
        rule.camp = camp
        rule.save()
        messages.success(request, "Preisregel wurde gespeichert.")
        return redirect("camp-detail", camp_id=camp.pk)
    return render(request, "billing/form.html", {"form": form, "title": "Preisregel anlegen"})


@editor_required
def expense_create(request, camp_id):
    camp = get_object_or_404(Camp, pk=camp_id)
    form = ExpenseForm(request.POST or None)
    form.fields["participant"].queryset = Participant.objects.filter(camp=camp)
    if request.method == "POST" and form.is_valid():
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
            rows = preview_participants(upload.file, upload.name)
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
