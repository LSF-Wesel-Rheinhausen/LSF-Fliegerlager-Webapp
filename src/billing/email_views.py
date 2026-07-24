import smtplib

from django.contrib import messages
from django.core import signing
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .email_credentials import EmailCredentialError
from .email_delivery import (
    has_valid_recipient_email,
    information_recipient_mapping,
    queue_information_email_batch,
    queue_settlement_email_batch,
    requeue_failed_email_delivery,
    resolve_information_recipients,
    resolve_settlement_recipients,
    send_configuration_test_email,
    settlement_recipient_mapping,
)
from .email_forms import EmailConfigurationForm, InformationEmailForm, SettlementEmailForm
from .models import Camp, CampAnnouncement, EmailBatch, EmailConfiguration, EmailDelivery, EmailTestLog, SettlementRun
from .notifications import queue_information_push_batch
from .permissions import admin_required

EMAIL_PREVIEW_SIGNING_SALT = "billing.manual-email-preview.v1"
EMAIL_PREVIEW_MAX_AGE_SECONDS = 60 * 60


def _preview_payload(
    *,
    kind: str,
    scope_id: int,
    user_id: int,
    subject: str,
    body: str,
    selected_ids: list[str],
    recipient_mapping: list[dict[str, object]],
) -> dict[str, object]:
    """Return the normalized state an administrator explicitly previewed."""
    return {
        "kind": kind,
        "scope_id": scope_id,
        "user_id": user_id,
        "subject": subject,
        "body": body,
        "selected_ids": sorted(int(selected_id) for selected_id in selected_ids),
        "recipient_mapping": recipient_mapping,
    }


def _sign_preview(payload: dict[str, object]) -> str:
    """Sign one preview state without storing server-side session data."""
    return signing.dumps(payload, salt=EMAIL_PREVIEW_SIGNING_SALT, compress=True)


def _matches_preview_token(token: str, payload: dict[str, object]) -> bool:
    """Return whether a non-expired token represents exactly the current form state."""
    try:
        signed_payload = signing.loads(
            token,
            salt=EMAIL_PREVIEW_SIGNING_SALT,
            max_age=EMAIL_PREVIEW_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return False
    return signed_payload == payload


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
            "recent_batches": EmailBatch.objects.select_related("camp", "created_by").annotate(
                delivery_count=Count("deliveries")
            )[:20],
            "recent_test_logs": EmailTestLog.objects.select_related("requested_by")[:10],
        },
    )


@admin_required
def information_email_compose(request, camp_id):
    """Preview and manually confirm one informational notification batch (E-Mail, Push, Kiosk)."""
    camp = get_object_or_404(Camp, pk=camp_id)
    configuration = EmailConfiguration.load()
    participants = list(camp.participants.filter(archived_at__isnull=True).order_by("last_name", "first_name", "pk"))
    eligible_ids = [participant.pk for participant in participants if has_valid_recipient_email(participant.email)]
    initial = {
        "subject": f"Information zu {camp.name} {camp.year}",
        "channels": "email",
        "show_in_kiosk": False,
        "participants": [str(participant_id) for participant_id in eligible_ids],
    }
    form = InformationEmailForm(
        request.POST or None,
        camp=camp,
        initial=initial,
    )
    preview = None
    preview_token = ""
    if request.method == "POST" and form.is_valid():
        channels = form.cleaned_data["channels"]
        if channels in {"email", "both"} and not configuration.enabled:
            form.add_error(None, "Der E-Mail-Versand ist in den Einstellungen deaktiviert.")
        else:
            preview = resolve_information_recipients(
                camp=camp,
                participant_ids=form.cleaned_data["participants"],
            )
            recipient_mapping = information_recipient_mapping(preview)
            preview_payload = _preview_payload(
                kind=EmailBatch.Kind.INFORMATION,
                scope_id=camp.pk,
                user_id=request.user.pk,
                subject=form.cleaned_data["subject"],
                body=form.cleaned_data["body"],
                selected_ids=form.cleaned_data["participants"],
                recipient_mapping=recipient_mapping,
            )
            preview_token = _sign_preview(preview_payload)
            if request.POST.get("action") == "confirm":
                if not _matches_preview_token(request.POST.get("preview_token", ""), preview_payload):
                    form.add_error(
                        None,
                        "Auswahl oder Inhalt wurde nach der Vorschau geändert. Bitte Vorschau erneut prüfen.",
                    )
                else:
                    success_parts = []
                    batch = None
                    if channels in {"email", "both"}:
                        try:
                            batch = queue_information_email_batch(
                                camp=camp,
                                participant_ids=form.cleaned_data["participants"],
                                subject=form.cleaned_data["subject"],
                                body=form.cleaned_data["body"],
                                created_by=request.user,
                                expected_recipient_mapping=recipient_mapping,
                            )
                            success_parts.append(f"{batch.deliveries.count()} E-Mail(s)")
                        except ValueError as error:
                            form.add_error(None, str(error))
                            batch = None

                    if not form.errors and channels in {"push", "both"}:
                        push_count = queue_information_push_batch(
                            camp=camp,
                            participant_ids=form.cleaned_data["participants"],
                            title=form.cleaned_data["subject"],
                            body=form.cleaned_data["body"],
                        )
                        success_parts.append(f"{push_count} Push-Benachrichtigung(en)")

                    if not form.errors and form.cleaned_data.get("show_in_kiosk"):
                        CampAnnouncement.objects.create(
                            camp=camp,
                            title=form.cleaned_data["subject"],
                            body=form.cleaned_data["body"],
                            created_by=request.user,
                        )
                        success_parts.append("Kiosk-Ankündigung")

                    if not form.errors and success_parts:
                        messages.success(
                            request,
                            f"Versand vorgemerkt: {', '.join(success_parts)}.",
                        )
                        if batch:
                            return redirect("email-batch-detail", batch_id=batch.pk)
                        return redirect("camp-detail", camp_id=camp.pk)
    missing_participants = [
        participant for participant in participants if not has_valid_recipient_email(participant.email)
    ]
    return render(
        request,
        "billing/information_email_compose.html",
        {
            "camp": camp,
            "configuration": configuration,
            "form": form,
            "missing_participants": missing_participants,
            "preview": preview,
            "preview_token": preview_token,
        },
    )


@admin_required
def settlement_email_compose(request, run_id):
    """Preview and manually confirm invoice PDFs from one immutable settlement run."""
    run = get_object_or_404(SettlementRun.objects.select_related("camp"), pk=run_id)
    configuration = EmailConfiguration.load()
    settlements = list(run.settlements.select_related("participant").order_by("participant_name", "pk"))
    eligible_ids = [
        settlement.pk for settlement in settlements if has_valid_recipient_email(settlement.participant.email)
    ]
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
    preview_token = ""
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
            recipient_mapping = settlement_recipient_mapping(preview)
            preview_payload = _preview_payload(
                kind=EmailBatch.Kind.SETTLEMENT,
                scope_id=run.pk,
                user_id=request.user.pk,
                subject=form.cleaned_data["subject"],
                body=form.cleaned_data["body"],
                selected_ids=form.cleaned_data["settlements"],
                recipient_mapping=recipient_mapping,
            )
            preview_token = _sign_preview(preview_payload)
            has_previously_sent = any(recipient.previously_sent for recipient in preview)
            has_already_queued = any(recipient.already_queued for recipient in preview)
            if request.POST.get("action") == "confirm":
                if not _matches_preview_token(request.POST.get("preview_token", ""), preview_payload):
                    form.add_error(
                        None,
                        "Auswahl oder Inhalt wurde nach der Vorschau geändert. Bitte Vorschau erneut prüfen.",
                    )
                elif has_already_queued:
                    form.add_error(None, "Mindestens eine Rechnung ist bereits zum Versand vorgemerkt.")
                elif not has_previously_sent or request.POST.get("confirm_resend") == "yes":
                    try:
                        batch = queue_settlement_email_batch(
                            run=run,
                            settlement_ids=form.cleaned_data["settlements"],
                            subject=form.cleaned_data["subject"],
                            body=form.cleaned_data["body"],
                            created_by=request.user,
                            expected_recipient_mapping=recipient_mapping,
                        )
                    except ValueError as error:
                        form.add_error(None, str(error))
                    else:
                        messages.success(
                            request,
                            f"{batch.deliveries.count()} Rechnung(en) wurden zum Versand vorgemerkt.",
                        )
                        return redirect("email-batch-detail", batch_id=batch.pk)
    missing_snapshots = [
        settlement for settlement in settlements if not has_valid_recipient_email(settlement.participant.email)
    ]
    return render(
        request,
        "billing/settlement_email_compose.html",
        {
            "camp": run.camp,
            "configuration": configuration,
            "form": form,
            "missing_snapshots": missing_snapshots,
            "preview": preview,
            "preview_token": preview_token,
            "has_previously_sent": has_previously_sent,
            "has_already_queued": has_already_queued,
            "run": run,
        },
    )


@admin_required
def email_batch_detail(request, batch_id):
    """Show the recipient-level status of a manually confirmed batch."""
    batch = get_object_or_404(EmailBatch.objects.select_related("camp", "created_by"), pk=batch_id)
    deliveries = batch.deliveries.select_related("settlement", "settlement__run").defer("attachment_content")
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
    try:
        requeue_failed_email_delivery(delivery)
    except ValueError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Die fehlgeschlagene E-Mail wurde erneut eingeplant.")
    return redirect("email-batch-detail", batch_id=delivery.batch_id)
