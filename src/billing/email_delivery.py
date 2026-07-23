import hashlib
import logging
import smtplib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from email.utils import formataddr
from typing import Any

from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape

from .exporters import settlement_snapshot_pdf_bytes
from .models import Camp, EmailBatch, EmailConfiguration, EmailDelivery, Participant, Settlement, SettlementRun

logger = logging.getLogger(__name__)
EMAIL_RETRY_DELAYS = (60, 300, 1800, 7200, 21600)
PROCESSING_LEASE = timedelta(minutes=15)


@dataclass(frozen=True)
class EmailDeliveryResult:
    """Summarize one bounded manual email outbox delivery batch."""

    sent: int = 0
    retried: int = 0
    failed: int = 0


@dataclass(frozen=True)
class InformationRecipient:
    """Describe one normalized recipient and the selected participant names."""

    email: str
    names: list[str]


@dataclass(frozen=True)
class SettlementRecipient:
    """Describe one selected invoice snapshot and its frozen delivery mapping."""

    settlement: Settlement
    email: str
    name: str
    filename: str
    previously_sent: bool


def _validate_message(subject: str, body: str) -> tuple[str, str]:
    clean_subject = subject.strip()
    clean_body = body.strip()
    if not clean_subject or len(clean_subject) > 160 or "\r" in clean_subject or "\n" in clean_subject:
        raise ValueError("Der Betreff ist ungültig.")
    if not clean_body or len(clean_body) > 10_000:
        raise ValueError("Die Nachricht ist ungültig.")
    return clean_subject, clean_body


def resolve_information_recipients(*, camp: Camp, participant_ids: Iterable[int]) -> list[InformationRecipient]:
    """Resolve an exact participant selection into unique normalized email recipients."""
    requested_ids = {int(participant_id) for participant_id in participant_ids}
    if not requested_ids:
        raise ValueError("Mindestens ein Empfänger muss ausgewählt werden.")
    participants = list(
        Participant.objects.filter(
            camp=camp,
            archived_at__isnull=True,
            pk__in=requested_ids,
        ).order_by("last_name", "first_name", "pk")
    )
    if {participant.pk for participant in participants} != requested_ids:
        raise ValueError("Die Empfängerauswahl enthält ungültige Teilnehmer.")

    recipients: dict[str, list[str]] = defaultdict(list)
    for participant in participants:
        normalized_email = participant.email.strip().casefold()
        validate_email(normalized_email)
        recipients[normalized_email].append(participant.full_name)
    return [InformationRecipient(email=email, names=sorted(names)) for email, names in sorted(recipients.items())]


def resolve_settlement_recipients(
    *,
    run: SettlementRun,
    settlement_ids: Iterable[int],
) -> list[SettlementRecipient]:
    """Resolve an exact settlement selection into recipient and attachment mappings."""
    requested_ids = {int(settlement_id) for settlement_id in settlement_ids}
    if not requested_ids:
        raise ValueError("Mindestens eine Rechnung muss ausgewählt werden.")
    settlements = list(
        Settlement.objects.select_related("participant")
        .filter(run=run, pk__in=requested_ids)
        .order_by("participant_name", "pk")
    )
    if {settlement.pk for settlement in settlements} != requested_ids:
        raise ValueError("Die Auswahl enthält ungültige Abrechnungen.")
    previously_sent_ids = set(
        EmailDelivery.objects.filter(
            settlement_id__in=requested_ids,
            status=EmailDelivery.Status.SENT,
        ).values_list("settlement_id", flat=True)
    )
    recipients = []
    for settlement in settlements:
        normalized_email = settlement.participant.email.strip().casefold()
        validate_email(normalized_email)
        recipients.append(
            SettlementRecipient(
                settlement=settlement,
                email=normalized_email,
                name=settlement.participant_name,
                filename=f"abrechnung-{settlement.pk}-v{run.version}.pdf",
                previously_sent=settlement.pk in previously_sent_ids,
            )
        )
    return recipients


@transaction.atomic
def queue_information_email_batch(
    *,
    camp: Camp,
    participant_ids: Iterable[int],
    subject: str,
    body: str,
    created_by: Any,
) -> EmailBatch:
    """Queue a manually confirmed information email once per normalized address."""
    clean_subject, clean_body = _validate_message(subject, body)
    recipients = resolve_information_recipients(camp=camp, participant_ids=participant_ids)

    batch = EmailBatch.objects.create(
        camp=camp,
        kind=EmailBatch.Kind.INFORMATION,
        subject=clean_subject,
        body=clean_body,
        created_by=created_by,
    )
    EmailDelivery.objects.bulk_create(
        [
            EmailDelivery(
                batch=batch,
                recipient_email=recipient.email,
                recipient_names=recipient.names,
                dedupe_key=f"information:{recipient.email}",
                subject=clean_subject,
                body_text=clean_body,
            )
            for recipient in recipients
        ]
    )
    return batch


@transaction.atomic
def queue_settlement_email_batch(
    *,
    run: SettlementRun,
    settlement_ids: Iterable[int],
    subject: str,
    body: str,
    created_by: Any,
) -> EmailBatch:
    """Queue selected immutable settlement PDFs for their current participant addresses."""
    clean_subject, clean_body = _validate_message(subject, body)
    recipients = resolve_settlement_recipients(run=run, settlement_ids=settlement_ids)

    deliveries: list[EmailDelivery] = []
    for recipient in recipients:
        deliveries.append(
            EmailDelivery(
                recipient_email=recipient.email,
                recipient_names=[recipient.name],
                settlement=recipient.settlement,
                dedupe_key=f"settlement:{recipient.settlement.pk}",
                subject=clean_subject,
                body_text=clean_body,
            )
        )

    batch = EmailBatch.objects.create(
        camp=run.camp,
        settlement_run=run,
        kind=EmailBatch.Kind.SETTLEMENT,
        subject=clean_subject,
        body=clean_body,
        created_by=created_by,
    )
    for delivery in deliveries:
        delivery.batch = batch
    EmailDelivery.objects.bulk_create(deliveries)
    return batch


def _smtp_connection(configuration: EmailConfiguration) -> Any:
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=configuration.host,
        port=configuration.port,
        username=configuration.username,
        password=configuration.get_password(),
        use_tls=configuration.security == EmailConfiguration.Security.STARTTLS,
        use_ssl=configuration.security == EmailConfiguration.Security.SSL,
        timeout=configuration.timeout,
    )


def _html_body(body: str) -> str:
    return f"<p>{escape(body).replace(chr(10), '<br>')}</p>"


def send_configuration_test_email(configuration: EmailConfiguration, recipient: str) -> None:
    """Send one explicit test message for a saved SMTP configuration."""
    normalized_recipient = recipient.strip().casefold()
    validate_email(normalized_recipient)
    body = "Diese Test-E-Mail bestätigt die gespeicherte SMTP-Konfiguration."
    connection = _smtp_connection(configuration)
    message = EmailMultiAlternatives(
        subject="Test der Fliegerlager-E-Mail-Einstellungen",
        body=body,
        from_email=formataddr((configuration.from_name, configuration.from_email)),
        to=[normalized_recipient],
        reply_to=[configuration.reply_to] if configuration.reply_to else None,
        connection=connection,
    )
    message.attach_alternative(_html_body(body), "text/html")
    message.send(fail_silently=False)


def requeue_failed_email_delivery(delivery: EmailDelivery) -> None:
    """Reset one permanently failed delivery after an explicit administrator action."""
    if delivery.status != EmailDelivery.Status.FAILED:
        raise ValueError("Nur fehlgeschlagene E-Mails können erneut eingeplant werden.")
    delivery.status = EmailDelivery.Status.PENDING
    delivery.attempts = 0
    delivery.next_attempt_at = timezone.now()
    delivery.processing_started_at = None
    delivery.last_error_code = ""
    delivery.save(
        update_fields=[
            "status",
            "attempts",
            "next_attempt_at",
            "processing_started_at",
            "last_error_code",
            "updated_at",
        ]
    )


def _send_delivery(
    delivery: EmailDelivery,
    *,
    configuration: EmailConfiguration,
    connection: Any,
) -> str:
    message = EmailMultiAlternatives(
        subject=delivery.subject,
        body=delivery.body_text,
        from_email=formataddr((configuration.from_name, configuration.from_email)),
        to=[delivery.recipient_email],
        reply_to=[configuration.reply_to] if configuration.reply_to else None,
        connection=connection,
    )
    message.attach_alternative(_html_body(delivery.body_text), "text/html")
    attachment_sha256 = ""
    settlement = delivery.settlement
    if settlement is not None:
        attachment = settlement_snapshot_pdf_bytes(settlement)
        run = settlement.run
        if run is None:
            raise ValueError("Invoice email requires a versioned settlement.")
        filename = f"abrechnung-{settlement.pk}-v{run.version}.pdf"
        message.attach(filename, attachment, "application/pdf")
        attachment_sha256 = hashlib.sha256(attachment).hexdigest()
    message.send(fail_silently=False)
    return attachment_sha256


def send_due_email_deliveries(*, batch_size: int = 25, connection: Any | None = None) -> EmailDeliveryResult:
    """Deliver manually confirmed email outbox entries without selecting recipients."""
    configuration = EmailConfiguration.load()
    if not configuration.enabled:
        return EmailDeliveryResult()
    now = timezone.now()
    EmailDelivery.objects.filter(
        status=EmailDelivery.Status.PROCESSING,
        processing_started_at__lt=now - PROCESSING_LEASE,
    ).update(
        status=EmailDelivery.Status.PENDING,
        processing_started_at=None,
        next_attempt_at=now,
    )
    delivery_ids = list(
        EmailDelivery.objects.filter(
            status=EmailDelivery.Status.PENDING,
            next_attempt_at__lte=now,
        )
        .order_by("next_attempt_at", "pk")
        .values_list("pk", flat=True)[:batch_size]
    )
    if not delivery_ids:
        return EmailDeliveryResult()
    mail_connection = connection or _smtp_connection(configuration)
    sent = retried = failed = 0
    for delivery_id in delivery_ids:
        claimed = EmailDelivery.objects.filter(
            pk=delivery_id,
            status=EmailDelivery.Status.PENDING,
            next_attempt_at__lte=now,
        ).update(
            status=EmailDelivery.Status.PROCESSING,
            processing_started_at=now,
        )
        if not claimed:
            continue
        delivery = EmailDelivery.objects.select_related(
            "settlement",
            "settlement__run",
            "settlement__run__camp",
        ).get(pk=delivery_id)
        try:
            attachment_sha256 = _send_delivery(
                delivery,
                configuration=configuration,
                connection=mail_connection,
            )
        except (smtplib.SMTPException, OSError) as error:
            delivery.attempts += 1
            smtp_code = getattr(error, "smtp_code", None)
            permanent = isinstance(smtp_code, int) and 500 <= smtp_code < 600
            if permanent or delivery.attempts >= len(EMAIL_RETRY_DELAYS):
                delivery.status = EmailDelivery.Status.FAILED
                failed += 1
            else:
                delivery.status = EmailDelivery.Status.PENDING
                delivery.next_attempt_at = now + timedelta(
                    seconds=EMAIL_RETRY_DELAYS[delivery.attempts - 1],
                )
                retried += 1
            delivery.processing_started_at = None
            delivery.last_error_code = str(smtp_code or "delivery_error")[:40]
            delivery.save(
                update_fields=[
                    "attempts",
                    "status",
                    "next_attempt_at",
                    "processing_started_at",
                    "last_error_code",
                    "updated_at",
                ]
            )
            logger.warning(
                "Email delivery failed",
                extra={
                    "email_delivery_id": delivery.pk,
                    "status_code": smtp_code,
                    "attempt": delivery.attempts,
                },
            )
            continue

        delivery.status = EmailDelivery.Status.SENT
        delivery.sent_at = now
        delivery.attempts += 1
        delivery.processing_started_at = None
        delivery.last_error_code = ""
        delivery.attachment_sha256 = attachment_sha256
        delivery.save(
            update_fields=[
                "status",
                "sent_at",
                "attempts",
                "processing_started_at",
                "last_error_code",
                "attachment_sha256",
                "updated_at",
            ]
        )
        sent += 1
    return EmailDeliveryResult(sent=sent, retried=retried, failed=failed)
