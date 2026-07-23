import logging
import smtplib
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.mail import get_connection
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse

from billing.email_credentials import EmailCredentialError
from billing.email_delivery import (
    EMAIL_RETRY_DELAYS,
    EmailDeliveryResult,
    queue_information_email_batch,
    queue_settlement_email_batch,
    send_due_email_deliveries,
)
from billing.models import EmailBatch, EmailConfiguration, EmailDelivery, EmailTestLog
from billing.permissions import EDITOR_GROUP
from billing.services import create_settlement_run
from tests.factories import CampFactory, ChargeFactory, GroupFactory, ParticipantFactory, SuperUserFactory, UserFactory


@pytest.mark.django_db
def test_email_configuration_encrypts_smtp_password(settings):
    settings.SECRET_KEY = "test-only-secret-key-with-more-than-fifty-characters-123456"
    admin = SuperUserFactory()
    configuration = EmailConfiguration.load()

    configuration.set_password("smtp-secret")
    configuration.updated_by = admin
    configuration.save()

    configuration.refresh_from_db()
    assert configuration.password_encrypted
    assert "smtp-secret" not in configuration.password_encrypted
    assert configuration.get_password() == "smtp-secret"
    assert configuration.updated_by == admin


@pytest.mark.django_db
def test_information_batch_groups_selected_participants_by_normalized_address():
    admin = SuperUserFactory()
    first = ParticipantFactory(first_name="Ada", last_name="Lovelace", email="Family@example.test")
    second = ParticipantFactory(
        camp=first.camp,
        first_name="Grace",
        last_name="Hopper",
        email="family@example.test",
    )

    batch = queue_information_email_batch(
        camp=first.camp,
        participant_ids=[first.pk, second.pk],
        subject="Treffpunkt",
        body="Wir treffen uns um 18 Uhr.",
        created_by=admin,
    )

    assert batch.kind == EmailBatch.Kind.INFORMATION
    assert batch.subject == "Treffpunkt"
    assert batch.body == "Wir treffen uns um 18 Uhr."
    assert batch.created_by == admin
    delivery = batch.deliveries.get()
    assert delivery.recipient_email == "family@example.test"
    assert delivery.recipient_names == ["Ada Lovelace", "Grace Hopper"]
    assert delivery.dedupe_key == "information:family@example.test"
    assert delivery.recipient_email not in str(delivery)
    assert str(delivery) == f"E-Mail-Zustellung {delivery.pk} (Ausstehend)"


@pytest.mark.django_db
def test_settlement_batch_maps_each_selected_snapshot_to_its_current_recipient():
    admin = SuperUserFactory()
    first = ParticipantFactory(first_name="Ada", last_name="Lovelace", email="ada@example.test")
    second = ParticipantFactory(camp=first.camp, first_name="Grace", last_name="Hopper", email="grace@example.test")
    ChargeFactory(participant=first)
    ChargeFactory(participant=second)
    run = create_settlement_run(first.camp, admin)
    first_snapshot = run.settlements.get(participant=first)
    second_snapshot = run.settlements.get(participant=second)

    batch = queue_settlement_email_batch(
        run=run,
        settlement_ids=[second_snapshot.pk],
        subject="Abrechnung",
        body="Im Anhang findest du deine Abrechnung.",
        created_by=admin,
    )

    assert batch.kind == EmailBatch.Kind.SETTLEMENT
    assert batch.settlement_run == run
    delivery = batch.deliveries.get()
    assert delivery.settlement == second_snapshot
    assert delivery.recipient_email == "grace@example.test"
    assert delivery.recipient_names == ["Grace Hopper"]
    assert delivery.dedupe_key == f"settlement:{second_snapshot.pk}"
    assert not batch.deliveries.filter(settlement=first_snapshot).exists()


@pytest.mark.django_db
def test_worker_sends_one_private_information_message_from_web_configuration():
    admin = SuperUserFactory()
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace", email="ADA@example.test")
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.port = 587
    configuration.username = "mailer"
    configuration.set_password("smtp-secret")
    configuration.security = EmailConfiguration.Security.STARTTLS
    configuration.from_name = "Fliegerlager"
    configuration.from_email = "lager@example.test"
    configuration.reply_to = "antwort@example.test"
    configuration.save()
    batch = queue_information_email_batch(
        camp=participant.camp,
        participant_ids=[participant.pk],
        subject="Treffpunkt",
        body="<Bitte> morgen um 8 Uhr.",
        created_by=admin,
    )

    result = send_due_email_deliveries(
        connection=get_connection("django.core.mail.backends.locmem.EmailBackend"),
    )

    assert result.sent == 1
    assert result.retried == 0
    assert result.failed == 0
    delivery = batch.deliveries.get()
    assert delivery.status == EmailDelivery.Status.SENT
    assert delivery.attempts == 1
    assert delivery.sent_at is not None
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["ada@example.test"]
    assert message.cc == []
    assert message.bcc == []
    assert message.from_email == "Fliegerlager <lager@example.test>"
    assert message.reply_to == ["antwort@example.test"]
    assert message.body == "<Bitte> morgen um 8 Uhr."
    assert message.alternatives[0].mimetype == "text/html"
    assert "&lt;Bitte&gt; morgen um 8 Uhr." in message.alternatives[0].content


@pytest.mark.django_db
def test_worker_attaches_pdf_from_selected_settlement_snapshot():
    admin = SuperUserFactory()
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace", email="ada@example.test")
    ChargeFactory(participant=participant)
    run = create_settlement_run(participant.camp, admin)
    snapshot = run.settlements.get()
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_name = "Fliegerlager"
    configuration.from_email = "lager@example.test"
    configuration.save()
    batch = queue_settlement_email_batch(
        run=run,
        settlement_ids=[snapshot.pk],
        subject="Abrechnung",
        body="Im Anhang findest du deine Abrechnung.",
        created_by=admin,
    )

    result = send_due_email_deliveries(
        connection=get_connection("django.core.mail.backends.locmem.EmailBackend"),
    )

    assert result.sent == 1
    message = mail.outbox[0]
    attachment = message.attachments[0]
    assert attachment.filename == f"abrechnung-{snapshot.pk}-v{run.version}.pdf"
    assert attachment.mimetype == "application/pdf"
    assert attachment.content.startswith(b"%PDF-")
    delivery = batch.deliveries.get()
    assert len(delivery.attachment_sha256) == 64


@pytest.mark.django_db
def test_admin_manages_smtp_configuration_without_rendering_stored_password(client):
    admin = SuperUserFactory()
    configuration = EmailConfiguration.load()
    configuration.set_password("old-secret")
    configuration.save()
    client.force_login(admin)

    response = client.get(reverse("email-settings"))

    assert response.status_code == 200
    assert b"SMTP-Host" in response.content
    assert b"old-secret" not in response.content
    assert configuration.password_encrypted.encode() not in response.content

    response = client.post(
        reverse("email-settings"),
        {
            "action": "save",
            "enabled": "on",
            "host": "smtp.example.test",
            "port": "465",
            "username": "mailer",
            "password": "",
            "security": EmailConfiguration.Security.SSL,
            "from_name": "Fliegerlager",
            "from_email": "lager@example.test",
            "reply_to": "antwort@example.test",
            "timeout": "15",
        },
    )

    assert response.status_code == 302
    configuration.refresh_from_db()
    assert configuration.enabled is True
    assert configuration.host == "smtp.example.test"
    assert configuration.port == 465
    assert configuration.security == EmailConfiguration.Security.SSL
    assert configuration.get_password() == "old-secret"
    assert configuration.updated_by == admin


@pytest.mark.django_db
@patch("billing.email_views.send_configuration_test_email")
def test_admin_saves_configuration_and_sends_explicit_test_message(send_test, client):
    admin = SuperUserFactory(email="admin@example.test")
    client.force_login(admin)

    response = client.post(
        reverse("email-settings"),
        {
            "action": "test",
            "enabled": "on",
            "host": "smtp.example.test",
            "port": "587",
            "username": "mailer",
            "password": "smtp-secret",
            "security": EmailConfiguration.Security.STARTTLS,
            "from_name": "Fliegerlager",
            "from_email": "lager@example.test",
            "reply_to": "",
            "timeout": "15",
            "test_recipient": "test-recipient@example.test",
        },
    )

    assert response.status_code == 302
    configuration = EmailConfiguration.load()
    send_test.assert_called_once_with(configuration, "test-recipient@example.test")
    assert configuration.last_tested_at is not None
    assert configuration.last_tested_by == admin
    test_log = EmailTestLog.objects.get()
    assert test_log.requested_by == admin
    assert test_log.recipient_email == "test-recipient@example.test"
    assert test_log.status == EmailTestLog.Status.SUCCESS
    assert test_log.error_code == ""


@pytest.mark.django_db
def test_editor_cannot_open_email_settings(client):
    editor = UserFactory()
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    client.force_login(editor)

    response = client.get(reverse("email-settings"))

    assert response.status_code == 302
    assert reverse("login") in response["Location"]


@pytest.mark.django_db
def test_admin_previews_and_confirms_exact_information_recipients(client):
    admin = SuperUserFactory()
    first = ParticipantFactory(first_name="Ada", last_name="Lovelace", email="Family@example.test")
    second = ParticipantFactory(
        camp=first.camp,
        first_name="Grace",
        last_name="Hopper",
        email="family@example.test",
    )
    missing = ParticipantFactory(camp=first.camp, first_name="Ohne", last_name="Adresse", email="")
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_email = "lager@example.test"
    configuration.set_password("smtp-secret")
    configuration.save()
    client.force_login(admin)
    url = reverse("information-email-compose", args=[first.camp_id])

    response = client.get(url)

    assert response.status_code == 200
    assert first.full_name.encode() in response.content
    assert second.full_name.encode() in response.content
    assert missing.full_name.encode() in response.content
    assert b"Keine E-Mail-Adresse" in response.content

    data = {
        "subject": "Treffpunkt",
        "body": "Wir treffen uns um 18 Uhr.",
        "participants": [str(first.pk), str(second.pk)],
    }
    preview = client.post(url, {**data, "action": "preview"})

    assert preview.status_code == 200
    assert b"Versandvorschau" in preview.content
    assert b"family@example.test" in preview.content
    assert b"Ada Lovelace" in preview.content
    assert b"Grace Hopper" in preview.content
    assert EmailBatch.objects.count() == 0

    confirmed = client.post(url, {**data, "action": "confirm"})

    batch = EmailBatch.objects.get()
    assert confirmed.status_code == 302
    assert confirmed["Location"] == reverse("email-batch-detail", args=[batch.pk])
    assert batch.deliveries.count() == 1


@pytest.mark.django_db
def test_admin_previews_and_confirms_selected_snapshot_recipient_mapping(client):
    admin = SuperUserFactory()
    recipient = ParticipantFactory(first_name="Ada", last_name="Lovelace", email="ada@example.test")
    missing = ParticipantFactory(camp=recipient.camp, first_name="Ohne", last_name="Adresse", email="")
    ChargeFactory(participant=recipient)
    ChargeFactory(participant=missing)
    run = create_settlement_run(recipient.camp, admin)
    snapshot = run.settlements.get(participant=recipient)
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_email = "lager@example.test"
    configuration.set_password("smtp-secret")
    configuration.save()
    client.force_login(admin)
    url = reverse("settlement-email-compose", args=[run.pk])

    response = client.get(url)

    assert response.status_code == 200
    assert b"Ada Lovelace" in response.content
    assert b"ada@example.test" in response.content
    assert b"Ohne Adresse" in response.content
    assert b"Keine E-Mail-Adresse" in response.content

    data = {
        "subject": "Abrechnung",
        "body": "Im Anhang findest du deine Abrechnung.",
        "settlements": [str(snapshot.pk)],
    }
    preview = client.post(url, {**data, "action": "preview"})

    assert preview.status_code == 200
    assert b"Versandvorschau" in preview.content
    assert b"ada@example.test" in preview.content
    assert f"abrechnung-{snapshot.pk}-v{run.version}.pdf".encode() in preview.content
    assert EmailBatch.objects.count() == 0

    confirmed = client.post(url, {**data, "action": "confirm"})

    batch = EmailBatch.objects.get()
    assert confirmed.status_code == 302
    assert confirmed["Location"] == reverse("email-batch-detail", args=[batch.pk])
    assert batch.settlement_run == run
    assert batch.deliveries.get().settlement == snapshot


@pytest.mark.django_db
def test_admin_manually_requeues_only_failed_delivery(client):
    admin = SuperUserFactory()
    participant = ParticipantFactory(email="ada@example.test")
    batch = queue_information_email_batch(
        camp=participant.camp,
        participant_ids=[participant.pk],
        subject="Treffpunkt",
        body="Wir treffen uns um 18 Uhr.",
        created_by=admin,
    )
    delivery = batch.deliveries.get()
    delivery.status = EmailDelivery.Status.FAILED
    delivery.attempts = 5
    delivery.last_error_code = "550"
    delivery.save()
    client.force_login(admin)

    response = client.post(reverse("email-delivery-retry", args=[delivery.pk]))

    assert response.status_code == 302
    assert response["Location"] == reverse("email-batch-detail", args=[batch.pk])
    delivery.refresh_from_db()
    assert delivery.status == EmailDelivery.Status.PENDING
    assert delivery.attempts == 0
    assert delivery.last_error_code == ""
    assert delivery.next_attempt_at is not None


@pytest.mark.django_db
@patch(
    "billing.management.commands.run_email_worker.send_due_email_deliveries",
    return_value=EmailDeliveryResult(sent=2, retried=1, failed=0),
)
def test_run_email_worker_processes_only_confirmed_outbox_once(send_due):
    output = StringIO()

    call_command("run_email_worker", stdout=output)

    send_due.assert_called_once_with()
    assert "2 gesendet, 1 erneut eingeplant, 0 fehlgeschlagen" in output.getvalue()


@pytest.mark.django_db
@patch("billing.email_delivery._smtp_connection")
def test_worker_does_not_open_smtp_connection_without_due_deliveries(smtp_connection):
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_email = "lager@example.test"
    configuration.set_password("smtp-secret")
    configuration.save()

    result = send_due_email_deliveries()

    assert result == EmailDeliveryResult()
    smtp_connection.assert_not_called()


@pytest.mark.django_db
@patch(
    "billing.management.commands.run_email_worker.send_due_email_deliveries",
    side_effect=EmailCredentialError("smtp-secret-must-not-appear"),
)
def test_run_email_worker_reports_credential_error_without_exposing_details(send_due):
    error_output = StringIO()

    call_command("run_email_worker", stderr=error_output)

    send_due.assert_called_once_with()
    assert "SMTP-Zugangsdaten" in error_output.getvalue()
    assert "smtp-secret-must-not-appear" not in error_output.getvalue()


@pytest.mark.django_db
def test_admin_navigation_links_manual_email_workflows(client):
    admin = SuperUserFactory()
    participant = ParticipantFactory(email="ada@example.test")
    ChargeFactory(participant=participant)
    run = create_settlement_run(participant.camp, admin)
    client.force_login(admin)

    camp_response = client.get(reverse("camp-detail", args=[participant.camp_id]))
    run_response = client.get(reverse("settlement-run-detail", args=[run.pk]))

    assert reverse("email-settings").encode() in camp_response.content
    assert reverse("information-email-compose", args=[participant.camp_id]).encode() in camp_response.content
    assert reverse("settlement-email-compose", args=[run.pk]).encode() in run_response.content


@pytest.mark.django_db
def test_repeated_invoice_delivery_requires_additional_confirmation(client):
    admin = SuperUserFactory()
    participant = ParticipantFactory(email="ada@example.test")
    ChargeFactory(participant=participant)
    run = create_settlement_run(participant.camp, admin)
    snapshot = run.settlements.get()
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_email = "lager@example.test"
    configuration.set_password("smtp-secret")
    configuration.save()
    previous_batch = queue_settlement_email_batch(
        run=run,
        settlement_ids=[snapshot.pk],
        subject="Abrechnung",
        body="Deine Abrechnung.",
        created_by=admin,
    )
    previous_batch.deliveries.update(status=EmailDelivery.Status.SENT)
    client.force_login(admin)
    url = reverse("settlement-email-compose", args=[run.pk])
    data = {
        "action": "confirm",
        "subject": "Abrechnung",
        "body": "Deine Abrechnung.",
        "settlements": [str(snapshot.pk)],
    }

    blocked = client.post(url, data)

    assert blocked.status_code == 200
    assert b"Bereits versendete Rechnungen erneut senden" in blocked.content
    assert EmailBatch.objects.count() == 1

    confirmed = client.post(url, {**data, "confirm_resend": "yes"})

    assert confirmed.status_code == 302
    assert EmailBatch.objects.count() == 2


@pytest.mark.django_db
def test_pending_invoice_delivery_blocks_duplicate_batch_and_web_confirmation(client):
    admin = SuperUserFactory()
    participant = ParticipantFactory(email="ada@example.test")
    ChargeFactory(participant=participant)
    run = create_settlement_run(participant.camp, admin)
    snapshot = run.settlements.get()
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_email = "lager@example.test"
    configuration.set_password("smtp-secret")
    configuration.save()
    queue_settlement_email_batch(
        run=run,
        settlement_ids=[snapshot.pk],
        subject="Abrechnung",
        body="Deine Abrechnung.",
        created_by=admin,
    )

    with pytest.raises(ValueError, match="bereits zum Versand vorgemerkt"):
        queue_settlement_email_batch(
            run=run,
            settlement_ids=[snapshot.pk],
            subject="Abrechnung",
            body="Deine Abrechnung.",
            created_by=admin,
        )

    client.force_login(admin)
    response = client.post(
        reverse("settlement-email-compose", args=[run.pk]),
        {
            "action": "confirm",
            "subject": "Abrechnung",
            "body": "Deine Abrechnung.",
            "settlements": [str(snapshot.pk)],
        },
    )

    assert response.status_code == 200
    assert b"bereits zum Versand vorgemerkt" in response.content
    assert EmailBatch.objects.count() == 1


@pytest.mark.django_db
def test_email_batch_requires_run_exactly_for_settlement_kind():
    admin = SuperUserFactory()
    participant = ParticipantFactory(email="ada@example.test")
    run = create_settlement_run(participant.camp, admin)

    with pytest.raises(IntegrityError), transaction.atomic():
        EmailBatch.objects.create(
            camp=participant.camp,
            kind=EmailBatch.Kind.SETTLEMENT,
            subject="Abrechnung",
            body="Nachricht",
            created_by=admin,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        EmailBatch.objects.create(
            camp=participant.camp,
            settlement_run=run,
            kind=EmailBatch.Kind.INFORMATION,
            subject="Information",
            body="Nachricht",
            created_by=admin,
        )


@pytest.mark.django_db
def test_worker_retries_temporary_smtp_failure_without_logging_recipient(caplog):
    admin = SuperUserFactory()
    participant = ParticipantFactory(email="private-person@example.test")
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_email = "lager@example.test"
    configuration.set_password("smtp-secret")
    configuration.save()
    batch = queue_information_email_batch(
        camp=participant.camp,
        participant_ids=[participant.pk],
        subject="Information",
        body="Nachricht",
        created_by=admin,
    )

    with (
        patch(
            "billing.email_delivery._send_delivery",
            side_effect=smtplib.SMTPResponseException(451, b"temporary failure"),
        ),
        caplog.at_level(logging.WARNING),
    ):
        result = send_due_email_deliveries(connection=object())

    assert result.retried == 1
    delivery = batch.deliveries.get()
    assert delivery.status == EmailDelivery.Status.PENDING
    assert delivery.attempts == 1
    assert delivery.last_error_code == "451"
    assert participant.email not in caplog.text


@pytest.mark.django_db
def test_worker_marks_permanent_smtp_failure_without_retry():
    admin = SuperUserFactory()
    participant = ParticipantFactory(email="private-person@example.test")
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_email = "lager@example.test"
    configuration.set_password("smtp-secret")
    configuration.save()
    batch = queue_information_email_batch(
        camp=participant.camp,
        participant_ids=[participant.pk],
        subject="Information",
        body="Nachricht",
        created_by=admin,
    )

    with patch(
        "billing.email_delivery._send_delivery",
        side_effect=smtplib.SMTPResponseException(550, b"recipient rejected"),
    ):
        result = send_due_email_deliveries(connection=object())

    assert result.failed == 1
    delivery = batch.deliveries.get()
    assert delivery.status == EmailDelivery.Status.FAILED
    assert delivery.attempts == 1
    assert delivery.last_error_code == "550"


@pytest.mark.django_db
def test_worker_schedules_final_configured_retry_delay():
    admin = SuperUserFactory()
    participant = ParticipantFactory(email="private-person@example.test")
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_email = "lager@example.test"
    configuration.set_password("smtp-secret")
    configuration.save()
    batch = queue_information_email_batch(
        camp=participant.camp,
        participant_ids=[participant.pk],
        subject="Information",
        body="Nachricht",
        created_by=admin,
    )
    delivery = batch.deliveries.get()
    delivery.attempts = len(EMAIL_RETRY_DELAYS) - 1
    delivery.save(update_fields=["attempts", "updated_at"])
    attempted_at = delivery.next_attempt_at + timedelta(minutes=1)

    with (
        patch("billing.email_delivery.timezone.now", return_value=attempted_at),
        patch(
            "billing.email_delivery._send_delivery",
            side_effect=smtplib.SMTPResponseException(451, b"temporary failure"),
        ),
    ):
        result = send_due_email_deliveries(connection=object())

    assert result.retried == 1
    assert result.failed == 0
    delivery.refresh_from_db()
    assert delivery.status == EmailDelivery.Status.PENDING
    assert delivery.attempts == len(EMAIL_RETRY_DELAYS)
    assert delivery.next_attempt_at == attempted_at + timedelta(seconds=EMAIL_RETRY_DELAYS[-1])


@pytest.mark.django_db
def test_email_settings_lists_recent_manual_batches(client):
    admin = SuperUserFactory()
    participant = ParticipantFactory(email="ada@example.test")
    batch = queue_information_email_batch(
        camp=participant.camp,
        participant_ids=[participant.pk],
        subject="Aktuelle Lagerinformation",
        body="Nachricht",
        created_by=admin,
    )
    client.force_login(admin)

    response = client.get(reverse("email-settings"))

    assert response.status_code == 200
    assert b"Aktuelle Lagerinformation" in response.content
    assert reverse("email-batch-detail", args=[batch.pk]).encode() in response.content


@pytest.mark.django_db
def test_information_compose_rejects_foreign_recipient_and_header_injection(client):
    admin = SuperUserFactory()
    local = ParticipantFactory(email="local@example.test")
    foreign = ParticipantFactory(camp=CampFactory(name="Anderes Lager", year=2026), email="foreign@example.test")
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_email = "lager@example.test"
    configuration.set_password("smtp-secret")
    configuration.save()
    client.force_login(admin)
    url = reverse("information-email-compose", args=[local.camp_id])

    response = client.post(
        url,
        {
            "action": "confirm",
            "subject": "Information\nBcc: attacker@example.test",
            "body": "Nachricht",
            "participants": [str(foreign.pk)],
        },
    )

    assert response.status_code == 200
    assert b"keinen Zeilenumbruch" in response.content
    assert b"g\xc3\xbcltige Auswahl" in response.content
    assert EmailBatch.objects.count() == 0
