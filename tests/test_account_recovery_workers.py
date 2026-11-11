"""Exercise the public kiosk recovery request through its delivery workers."""

import json
import re
from unittest.mock import Mock, patch

import pytest
from django.core import mail
from django.core.mail import get_connection
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from billing.email_delivery import send_due_email_deliveries
from billing.models import (
    AccountRecoveryDeliveryRequest,
    AccountRecoveryToken,
    EmailConfiguration,
    EmailDelivery,
    Participant,
    ParticipantFamilyMember,
    PushMessage,
    PushSubscription,
)
from billing.notifications import send_due_push_messages
from tests.factories import ParticipantFactory, ParticipantFamilyMemberFactory


@pytest.mark.django_db
@pytest.mark.parametrize("owner_kind", ["participant", "companion"])
@pytest.mark.parametrize("request_kind", ["dropdown", "email"])
@pytest.mark.parametrize("channels", ["email", "push", "both"])
def test_kiosk_recovery_worker_pipeline(kiosk_client, settings, owner_kind, request_kind, channels):
    """Each public request resolves to exactly the selected owner and requested channels."""
    settings.WEB_PUSH_ENABLED = channels in {"push", "both"}
    settings.WEB_PUSH_ALLOWED_ORIGINS = ["https://push.example.test"]
    configuration = EmailConfiguration.load()
    configuration.enabled = channels in {"email", "both"}
    configuration.host = "smtp.example.test"
    configuration.from_email = "lager@example.test"
    configuration.save()

    participant = ParticipantFactory(email="teilnehmer@example.test")
    if owner_kind == "participant":
        owner = participant
        subscription_owner = {"participant": participant}
        expected_kind = AccountRecoveryToken.Kind.PARTICIPANT_PIN
        picker_value = f"participant-{participant.pk}"
    else:
        owner = ParticipantFamilyMemberFactory(
            guardian=participant,
            email="begleitung@example.test",
            role=ParticipantFamilyMember.Role.COMPANION,
            is_active=True,
        )
        subscription_owner = {"family_member": owner}
        expected_kind = AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN
        picker_value = f"family-{owner.pk}"
    owner.pin.set_pin("2468")
    owner.pin.save()
    if settings.WEB_PUSH_ENABLED:
        PushSubscription.objects.create(
            **subscription_owner,
            endpoint=f"https://push.example.test/{owner_kind}-{request_kind}-{channels}",
            p256dh="test-key",
            auth="test-auth",
            identity_verified=True,
        )

    post_data = {"participant": picker_value} if request_kind == "dropdown" else {"email": owner.email}
    response = kiosk_client.post(reverse("kiosk-pin-recovery-request"), post_data)
    assert response.status_code == 302
    request = AccountRecoveryDeliveryRequest.objects.get()
    assert request.kind == (
        AccountRecoveryDeliveryRequest.Kind.KIOSK_PIN_PICKER
        if request_kind == "dropdown"
        else AccountRecoveryDeliveryRequest.Kind.KIOSK_PIN_EMAIL
    )

    call_command("run_account_recovery_worker")
    assert not AccountRecoveryDeliveryRequest.objects.exists()
    expected_email = channels in {"email", "both"}
    expected_push = channels in {"push", "both"}
    expected_tokens = int(expected_email) + int(expected_push)
    assert EmailDelivery.objects.count() == int(expected_email)
    assert PushMessage.objects.count() == int(expected_push)
    assert AccountRecoveryToken.objects.count() == expected_tokens
    assert set(AccountRecoveryToken.objects.values_list("kind", flat=True)) == {expected_kind}
    assert set(AccountRecoveryToken.objects.values_list("delivery_channel", flat=True)) == (
        {AccountRecoveryToken.DeliveryChannel.EMAIL, AccountRecoveryToken.DeliveryChannel.PUSH}
        if channels == "both"
        else {AccountRecoveryToken.DeliveryChannel.EMAIL}
        if expected_email
        else {AccountRecoveryToken.DeliveryChannel.PUSH}
        if expected_push
        else set()
    )

    if expected_email:
        with patch(
            "billing.email_delivery._smtp_connection",
            return_value=get_connection("django.core.mail.backends.locmem.EmailBackend"),
        ):
            call_command("run_email_worker")
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [owner.email]
        delivery = EmailDelivery.objects.get()
        assert delivery.status == EmailDelivery.Status.SENT
        token = delivery.account_recovery
        assert token.expires_at is not None
    else:
        assert send_due_email_deliveries().sent == 0
        assert not mail.outbox

    if expected_push:
        with patch("billing.notifications.webpush", return_value=Mock(status_code=201)) as webpush:
            call_command("run_push_worker")
        webpush.assert_called_once()
        message = PushMessage.objects.get()
        assert message.status == PushMessage.Status.SENT
        assert message.account_recovery.delivery_channel == AccountRecoveryToken.DeliveryChannel.PUSH
        push_url = json.loads(webpush.call_args.kwargs["data"])["url"]
    else:
        with patch("billing.notifications.webpush") as webpush:
            assert send_due_push_messages().sent == 0
        webpush.assert_not_called()

    call_command("run_account_recovery_worker")
    with patch(
        "billing.email_delivery._smtp_connection",
        return_value=get_connection("django.core.mail.backends.locmem.EmailBackend"),
    ):
        call_command("run_email_worker")
    with patch("billing.notifications.webpush") as duplicate_push:
        call_command("run_push_worker")
    duplicate_push.assert_not_called()
    assert len(mail.outbox) == int(expected_email)
    assert EmailDelivery.objects.count() == int(expected_email)
    assert PushMessage.objects.count() == int(expected_push)
    assert AccountRecoveryToken.objects.count() == expected_tokens

    confirm_paths = []
    if expected_email:
        email_url = re.search(r"https?://[^\s]+", mail.outbox[0].body).group(0)
        confirm_paths.append(re.sub(r"^https?://[^/]+", "", email_url))
    if expected_push:
        confirm_paths.append(push_url)
    for path in confirm_paths:
        assert Client().get(path).status_code == 200

    if confirm_paths:
        response = Client().post(
            confirm_paths[0],
            {"pin": "9753", "pin_repeat": "9753"},
        )
        assert response.status_code == 302
        owner.refresh_from_db()
        assert owner.pin.check_pin("9753")
        assert AccountRecoveryToken.objects.filter(used_at__isnull=False).exists()
        for path in confirm_paths:
            assert Client().get(path).status_code != 200

    assert (
        AccountRecoveryToken.objects.filter(
            participant=owner if isinstance(owner, Participant) else None,
            family_member=owner if isinstance(owner, ParticipantFamilyMember) else None,
        ).count()
        == expected_tokens
    )
