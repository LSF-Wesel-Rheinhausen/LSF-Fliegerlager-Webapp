import smtplib

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .email_credentials import EmailCredentialError
from .email_delivery import (
    queue_information_email_batch,
    queue_settlement_email_batch,
    requeue_failed_email_delivery,
    resolve_information_recipients,
    resolve_settlement_recipients,
    send_configuration_test_email,
)
from .email_forms import EmailConfigurationForm, InformationEmailForm, SettlementEmailForm
from .models import Camp, EmailBatch, EmailConfiguration, EmailDelivery, EmailTestLog, SettlementRun
from .permissions import admin_required


@admin_required
def email_settings(request):
    """Allow administrators to manage the encrypted global SMTP configuration."""
    configuration = EmailConfiguration.load()
    form = EmailConfigurationForm(
        request.POST or None,
        instance=configuration,
        initial={"test_recipient": request.user.email},
    )
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action")
        if action == "test" and not form.cleaned_data["test_recipient"]:
            form.add_error("test_recipient", "Für die Test-E-Mail ist eine Empfängeradresse erforderlich.")
        elif action in {"save", "test"}:
            configuration = form.save(updated_by=request.user)
            if action == "test":
                try:
                    send_configuration_test_email(configuration, form.cleaned_data["test_recipient"])
                except (EmailCredentialError, smtplib.SMTPException, OSError) as error:
                    error_code = getattr(error, "smtp_code", None) or type(error).__name__
                    EmailTestLog.objects.create(
                        requested_by=request.user,
                        recipient_email=form.cleaned_data["test_recipient"].strip().casefold(),
                        status=EmailTestLog.Status.FAILED,
                        error_code=str(error_code)[:40],
                    )
                    form.add_error(
                        None,
                        "Die Test-E-Mail konnte nicht gesendet werden. Bitte Verbindungseinstellungen prüfen.",
                    )
                else:
                    EmailTestLog.objects.create(
                        requested_by=request.user,
                        recipient_email=form.cleaned_data["test_recipient"].strip().casefold(),
                        status=EmailTestLog.Status.SUCCESS,
                    )
                    configuration.last_tested_at = timezone.now()
                    configuration.last_tested_by = request.user
                    configuration.save(update_fields=["last_tested_at", "last_tested_by", "updated_at"])
                    messages.success(request, "Die Test-E-Mail wurde gesendet.")
                    return redirect("email-settings")
            else:
                messages.success(request, "E-Mail-Einstellungen wurden gespeichert.")
                return redirect("email-settings")
    return render(
        request,
        "billing/email_settings.html",
        {
            "form": form,
            "configuration": configuration,
            "recent_batches": EmailBatch.objects.select_related("camp", "created_by").prefetch_related("deliveries")[
                :20
            ],
            "recent_test_logs": EmailTestLog.objects.select_related("requested_by")[:10],
        },
    )


@admin_required
def information_email_compose(request, camp_id):
    """Preview and manually confirm one informational email batch."""
    camp = get_object_or_404(Camp, pk=camp_id)
    configuration = EmailConfiguration.load()
    eligible_ids = list(
        camp.participants.filter(archived_at__isnull=True).exclude(email="").values_list("pk", flat=True)
    )
    initial = {
        "subject": f"Information zu {camp.name} {camp.year}",
        "participants": [str(participant_id) for participant_id in eligible_ids],
    }
    form = InformationEmailForm(
        request.POST or None,
        camp=camp,
        initial=initial,
    )
    preview = None
    if request.method == "POST" and form.is_valid():
        if not configuration.enabled:
            form.add_error(None, "Der E-Mail-Versand ist in den Einstellungen deaktiviert.")
        else:
            preview = resolve_information_recipients(
                camp=camp,
                participant_ids=form.cleaned_data["participants"],
            )
            if request.POST.get("action") == "confirm":
                batch = queue_information_email_batch(
                    camp=camp,
                    participant_ids=form.cleaned_data["participants"],
                    subject=form.cleaned_data["subject"],
                    body=form.cleaned_data["body"],
                    created_by=request.user,
                )
                messages.success(request, f"{batch.deliveries.count()} E-Mail(s) wurden zum Versand vorgemerkt.")
                return redirect("email-batch-detail", batch_id=batch.pk)
    missing_participants = camp.participants.filter(
        archived_at__isnull=True,
        email="",
    ).order_by("last_name", "first_name")
    return render(
        request,
        "billing/information_email_compose.html",
        {
            "camp": camp,
            "configuration": configuration,
            "form": form,
            "missing_participants": missing_participants,
            "preview": preview,
        },
    )


@admin_required
def settlement_email_compose(request, run_id):
    """Preview and manually confirm invoice PDFs from one immutable settlement run."""
    run = get_object_or_404(SettlementRun.objects.select_related("camp"), pk=run_id)
    configuration = EmailConfiguration.load()
    eligible_ids = list(run.settlements.exclude(participant__email="").values_list("pk", flat=True))
    initial = {
        "subject": f"Abrechnung {run.camp.name} {run.camp.year} · V{run.version}",
        "body": "Im Anhang findest du deine Abrechnung.",
        "settlements": [str(settlement_id) for settlement_id in eligible_ids],
    }
    form = SettlementEmailForm(
        request.POST or None,
        run=run,
        initial=initial,
    )
    preview = None
    has_previously_sent = False
    has_already_queued = False
    if request.method == "POST" and form.is_valid():
        if not configuration.enabled:
            form.add_error(None, "Der E-Mail-Versand ist in den Einstellungen deaktiviert.")
        else:
            preview = resolve_settlement_recipients(
                run=run,
                settlement_ids=form.cleaned_data["settlements"],
            )
            has_previously_sent = any(recipient.previously_sent for recipient in preview)
            has_already_queued = any(recipient.already_queued for recipient in preview)
            if request.POST.get("action") == "confirm":
                if has_already_queued:
                    form.add_error(None, "Mindestens eine Rechnung ist bereits zum Versand vorgemerkt.")
                elif not has_previously_sent or request.POST.get("confirm_resend") == "yes":
                    try:
                        batch = queue_settlement_email_batch(
                            run=run,
                            settlement_ids=form.cleaned_data["settlements"],
                            subject=form.cleaned_data["subject"],
                            body=form.cleaned_data["body"],
                            created_by=request.user,
                        )
                    except ValueError as error:
                        form.add_error(None, str(error))
                    else:
                        messages.success(
                            request,
                            f"{batch.deliveries.count()} Rechnung(en) wurden zum Versand vorgemerkt.",
                        )
                        return redirect("email-batch-detail", batch_id=batch.pk)
    missing_snapshots = (
        run.settlements.select_related("participant")
        .filter(
            participant__email="",
        )
        .order_by("participant_name", "pk")
    )
    return render(
        request,
        "billing/settlement_email_compose.html",
        {
            "camp": run.camp,
            "configuration": configuration,
            "form": form,
            "missing_snapshots": missing_snapshots,
            "preview": preview,
            "has_previously_sent": has_previously_sent,
            "has_already_queued": has_already_queued,
            "run": run,
        },
    )


@admin_required
def email_batch_detail(request, batch_id):
    """Show the recipient-level status of a manually confirmed batch."""
    batch = get_object_or_404(EmailBatch.objects.select_related("camp", "created_by"), pk=batch_id)
    deliveries = batch.deliveries.select_related("settlement", "settlement__run").all()
    counts = deliveries.aggregate(
        pending=Count("pk", filter=Q(status=EmailDelivery.Status.PENDING)),
        processing=Count("pk", filter=Q(status=EmailDelivery.Status.PROCESSING)),
        sent=Count("pk", filter=Q(status=EmailDelivery.Status.SENT)),
        failed=Count("pk", filter=Q(status=EmailDelivery.Status.FAILED)),
    )
    return render(
        request,
        "billing/email_batch_detail.html",
        {
            "batch": batch,
            "camp": batch.camp,
            "deliveries": deliveries,
            "counts": counts,
        },
    )


@admin_required
@require_POST
def email_delivery_retry(request, delivery_id):
    """Requeue one failed delivery after an explicit administrator action."""
    delivery = get_object_or_404(EmailDelivery.objects.select_related("batch"), pk=delivery_id)
    if delivery.status != EmailDelivery.Status.FAILED:
        messages.error(request, "Nur fehlgeschlagene E-Mails können erneut eingeplant werden.")
    else:
        requeue_failed_email_delivery(delivery)
        messages.success(request, "Die fehlgeschlagene E-Mail wurde erneut eingeplant.")
    return redirect("email-batch-detail", batch_id=delivery.batch_id)
