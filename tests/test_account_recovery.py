import hashlib
import json
import smtplib
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import pytest
from django.contrib.auth import authenticate
from django.core import mail
from django.core.mail import get_connection
from django.db.models import QuerySet
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from billing.email_delivery import queue_account_recovery_email, send_due_email_deliveries
from billing.kiosk_access import KIOSK_PARTICIPANT_SESSION_KEY
from billing.kiosk_security import check_login_rate_limit, consume_login_failure, is_login_locked_out
from billing.models import (
    AccountRecoveryToken,
    EmailBatch,
    EmailConfiguration,
    EmailDelivery,
    ParticipantFamilyMember,
    ParticipantFamilyMemberPin,
    ParticipantPin,
    PushMessage,
    PushSubscription,
)
from billing.notifications import send_due_push_messages
from billing.recovery_tokens import activate_account_recovery_token, create_account_recovery_token
from tests.factories import ParticipantFactory, ParticipantFamilyMemberFactory, SuperUserFactory, UserFactory


def _send_recovery_emails(*, expected_failed: int = 0):
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_name = "Fliegerlager"
    configuration.from_email = "lager@example.test"
    configuration.save()
    result = send_due_email_deliveries(connection=get_connection("django.core.mail.backends.locmem.EmailBackend"))
    assert result.failed == expected_failed
    return result


@pytest.mark.django_db
def test_admin_login_links_to_password_recovery(client):
    SuperUserFactory()
    response = client.get(reverse("login"))

    assert response.status_code == 200
    assert reverse("account-recovery-request") in response.content.decode()
    assert "Passwort vergessen?" in response.content.decode()


@pytest.mark.django_db
def test_kiosk_login_links_to_pin_recovery(kiosk_client):
    response = kiosk_client.get(reverse("kiosk-login"))

    assert response.status_code == 200
    assert reverse("kiosk-pin-recovery-request") in response.content.decode()
    assert "PIN vergessen?" in response.content.decode()


@pytest.mark.django_db
def test_kiosk_recovery_reuses_public_login_identity_choices(kiosk_client):
    participant = ParticipantFactory(first_name="Visible", last_name="Pilot")

    response = kiosk_client.get(reverse("kiosk-pin-recovery-request"))

    assert response.status_code == 200
    assert f'value="participant-{participant.pk}"' in response.content.decode()
    assert participant.full_name in response.content.decode()


@pytest.mark.django_db
def test_admin_recovery_queues_email_and_push_without_disclosing_account(client, settings):
    settings.WEB_PUSH_ENABLED = True
    user = UserFactory(username="ada", email="Ada@example.test", password="old-password")
    subscription = PushSubscription.objects.create(
        user=user,
        endpoint="https://push.example.test/admin-recovery",
        p256dh="key",
        auth="auth",
        categories=[],
    )

    response = client.post(reverse("account-recovery-request"), {"identifier": " ada@example.test "}, follow=True)

    assert response.status_code == 200
    assert "Falls ein aktives Konto passt" in response.content.decode()
    delivery = EmailDelivery.objects.get()
    assert delivery.recipient_email == "ada@example.test"
    assert delivery.subject == "Passwort zurücksetzen"
    message = PushMessage.objects.get(subscription=subscription)
    assert message.category == "account_security"
    assert message.title == "Passwort zurücksetzen"
    recovery_tokens = list(AccountRecoveryToken.objects.order_by("pk"))
    assert len(recovery_tokens) == 2
    assert all(recovery.expires_at is None for recovery in recovery_tokens)

    _send_recovery_emails()
    with patch("billing.notifications.webpush") as webpush:
        assert send_due_push_messages().sent == 1
    email_path = urlsplit(mail.outbox[0].body.splitlines()[-1]).path
    push_path = json.loads(webpush.call_args.kwargs["data"])["url"]
    email_secret = email_path.rstrip("/").rsplit("/", maxsplit=1)[-1]
    push_secret = push_path.rstrip("/").rsplit("/", maxsplit=1)[-1]
    html_body = mail.outbox[0].alternatives[0].content
    delivery.refresh_from_db()
    message.refresh_from_db()
    assert email_secret in html_body
    assert email_secret not in delivery.body_text
    assert email_secret not in delivery.batch.body
    assert push_secret not in message.target_url
    assert email_secret != push_secret

    unknown_response = client.post(
        reverse("account-recovery-request"),
        {"identifier": "missing@example.test"},
        follow=True,
    )

    assert unknown_response.status_code == response.status_code
    assert "Falls ein aktives Konto passt" in unknown_response.content.decode()
    assert EmailDelivery.objects.count() == 1
    assert PushMessage.objects.count() == 1


@pytest.mark.django_db
def test_admin_recovery_token_is_single_use_and_clears_login_lockout(client):
    user = UserFactory(username="locked-admin", email="locked@example.test", password="old-password")
    request = RequestFactory().post("/login/", REMOTE_ADDR="192.0.2.10")
    for _ in range(5):
        consume_login_failure(request, username=user.username)
    assert is_login_locked_out(user.username) is True
    assert check_login_rate_limit(request, username=user.username) is False
    client.post(
        reverse("account-recovery-request"),
        {"identifier": user.username},
        REMOTE_ADDR="192.0.2.10",
        follow=True,
    )
    _send_recovery_emails()
    path = urlsplit(mail.outbox[0].body.splitlines()[-1]).path

    reset_page = client.get(path)
    assert reset_page.status_code == 200
    assert reset_page["Cache-Control"] == "no-store"
    assert reset_page["Referrer-Policy"] == "no-referrer"
    assert path.encode() not in reset_page.content
    reset_response = client.post(
        path,
        {"new_password1": "A-secure-new-password-601", "new_password2": "A-secure-new-password-601"},
        REMOTE_ADDR="192.0.2.10",
        follow=True,
    )

    assert reset_response.status_code == 200
    assert "Passwort wurde geändert" in reset_response.content.decode()
    assert authenticate(username=user.username, password="A-secure-new-password-601") == user
    assert is_login_locked_out(user.username) is False
    assert check_login_rate_limit(request, username=user.username) is True
    assert client.get(path).status_code == 400


@pytest.mark.django_db
def test_kiosk_recovery_queues_both_channels_and_sets_a_new_pin(kiosk_client, settings):
    settings.WEB_PUSH_ENABLED = True
    participant = ParticipantFactory(email="Pilot@example.test")
    participant.pin.set_pin("2468")
    participant.pin.save()
    subscription = PushSubscription.objects.create(
        participant=participant,
        endpoint="https://push.example.test/kiosk-recovery",
        p256dh="key",
        auth="auth",
        categories=[],
    )

    response = kiosk_client.post(
        reverse("kiosk-pin-recovery-request"),
        {"email": " pilot@example.test "},
        follow=True,
    )

    assert response.status_code == 200
    assert "Falls ein aktives Konto passt" in response.content.decode()
    message = PushMessage.objects.get(subscription=subscription)
    assert message.title == "PIN zurücksetzen"
    _send_recovery_emails()
    path = urlsplit(mail.outbox[0].body.splitlines()[-1]).path

    reset_response = kiosk_client.post(path, {"pin": "8642", "pin_repeat": "8642"}, follow=True)

    assert reset_response.status_code == 200
    assert "PIN wurde geändert" in reset_response.content.decode()
    participant.pin.refresh_from_db()
    assert participant.pin.check_pin("8642") is True
    assert kiosk_client.get(path).status_code == 400


@pytest.mark.django_db
def test_recovery_push_targets_only_the_companion_account(kiosk_client, settings):
    settings.WEB_PUSH_ENABLED = True
    guardian = ParticipantFactory(email="guardian@example.test", first_name="Grace", last_name="Guardian")
    companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        email="companion@example.test",
        first_name="Connie",
        last_name="Companion",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    PushSubscription.objects.create(
        family_member=companion,
        endpoint="https://push.example.test/companion-identity",
        p256dh="key",
        auth="auth",
        categories=[],
    )

    kiosk_client.post(reverse("kiosk-pin-recovery-request"), {"email": companion.email})

    message = PushMessage.objects.get()
    assert message.subscription.family_member_id == companion.pk
    assert message.subscription.participant_id is None


@pytest.mark.django_db
def test_recovery_email_identifier_is_not_parsed_as_picker_token(kiosk_client):
    participant = ParticipantFactory(email="participant-1@example.test")

    response = kiosk_client.post(
        reverse("kiosk-pin-recovery-request"),
        {"email": participant.email},
    )

    assert response.status_code == 302
    assert AccountRecoveryToken.objects.filter(participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_recovery_delivers_to_all_matching_participants(kiosk_client):
    first_participant = ParticipantFactory(email="shared-many@example.test", first_name="Pilot0")
    for index in range(1, 11):
        ParticipantFactory(
            camp=first_participant.camp,
            email="shared-many@example.test",
            first_name=f"Pilot{index}",
        )

    response = kiosk_client.post(
        reverse("kiosk-pin-recovery-request"),
        {"email": "shared-many@example.test"},
    )

    assert response.status_code == 302
    assert EmailDelivery.objects.count() == 11


@pytest.mark.django_db
@pytest.mark.parametrize("owner_kind", ["participant", "companion"])
def test_kiosk_recovery_revokes_existing_kiosk_session(kiosk_client, owner_kind):
    participant = ParticipantFactory(email="owner@example.test")
    participant.pin.set_pin("2468")
    participant.pin.save()
    if owner_kind == "participant":
        owner = participant
        login_token = f"participant-{participant.pk}"
    else:
        owner = ParticipantFamilyMemberFactory(
            guardian=participant,
            email="companion@example.test",
            role=ParticipantFamilyMember.Role.COMPANION,
        )
        owner.pin.set_pin("2468")
        owner.pin.save()
        login_token = f"family-{owner.pk}"

    login_response = kiosk_client.post(reverse("kiosk-login"), {"participant": login_token, "pin": "2468"})
    assert login_response.status_code == 302

    kiosk_client.post(reverse("kiosk-pin-recovery-request"), {"email": owner.email})
    _send_recovery_emails()
    path = urlsplit(mail.outbox[0].body.splitlines()[-1]).path
    kiosk_client.post(path, {"pin": "8642", "pin_repeat": "8642"})

    home_response = kiosk_client.get(reverse("kiosk-home"))
    assert home_response.status_code == 302
    assert home_response.url == reverse("kiosk-login")
    assert KIOSK_PARTICIPANT_SESSION_KEY not in kiosk_client.session


@pytest.mark.django_db
def test_recovery_rejects_expired_tokens_without_changing_credentials(client, settings):
    settings.ACCOUNT_RECOVERY_TIMEOUT_SECONDS = 60
    user = UserFactory(email="expired@example.test", password="old-password")
    requested_at = timezone.now()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("billing.account_recovery.timezone.now", lambda: requested_at)
        client.post(reverse("account-recovery-request"), {"identifier": user.email})
    delivered_at = requested_at + timezone.timedelta(hours=2)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("billing.recovery_tokens.timezone.now", lambda: delivered_at)
        _send_recovery_emails()
    path = urlsplit(mail.outbox[0].body.splitlines()[-1]).path
    recovery = AccountRecoveryToken.objects.get()
    assert recovery.expires_at == delivered_at + timezone.timedelta(seconds=60)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "billing.account_recovery.timezone.now",
            lambda: delivered_at + timezone.timedelta(seconds=61),
        )
        response = client.post(
            path,
            {"new_password1": "Another-secure-password-601", "new_password2": "Another-secure-password-601"},
        )

    assert response.status_code == 400
    assert authenticate(username=user.username, password="old-password") == user


@pytest.mark.django_db
def test_recovery_email_retry_rotates_token_and_restarts_expiry(client, settings):
    settings.ACCOUNT_RECOVERY_TIMEOUT_SECONDS = 60
    user = UserFactory(email="retry@example.test")
    client.post(reverse("account-recovery-request"), {"identifier": user.email})
    configuration = EmailConfiguration.load()
    configuration.enabled = True
    configuration.host = "smtp.example.test"
    configuration.from_name = "Fliegerlager"
    configuration.from_email = "lager@example.test"
    configuration.save()
    connection = Mock()
    connection.send_messages.side_effect = [smtplib.SMTPException("temporarily unavailable"), 1]
    first_attempt_at = timezone.now()

    with (
        patch("billing.email_delivery.timezone.now", return_value=first_attempt_at),
        patch("billing.recovery_tokens.timezone.now", return_value=first_attempt_at),
    ):
        assert send_due_email_deliveries(connection=connection).retried == 1
    recovery = AccountRecoveryToken.objects.get()
    first_digest = recovery.token_digest
    assert recovery.expires_at == first_attempt_at + timezone.timedelta(seconds=60)

    second_attempt_at = first_attempt_at + timezone.timedelta(seconds=61)
    with (
        patch("billing.email_delivery.timezone.now", return_value=second_attempt_at),
        patch("billing.recovery_tokens.timezone.now", return_value=second_attempt_at),
    ):
        assert send_due_email_deliveries(connection=connection).sent == 1
    recovery.refresh_from_db()
    assert recovery.token_digest != first_digest
    assert recovery.expires_at == second_attempt_at + timezone.timedelta(seconds=60)


@pytest.mark.django_db
def test_recovery_requests_are_rate_limited_per_client_without_disclosure(client, settings):
    settings.ACCOUNT_RECOVERY_MAX_REQUESTS = 3
    settings.ACCOUNT_RECOVERY_REQUEST_WINDOW_SECONDS = 900
    user = UserFactory(email="rate-limit@example.test")

    responses = [
        client.post(
            reverse("account-recovery-request"),
            {"identifier": user.email},
            REMOTE_ADDR="192.0.2.40",
        )
        for _ in range(4)
    ]

    assert [response.status_code for response in responses] == [302, 302, 302, 429]
    assert responses[-1]["Retry-After"] == "900"
    assert EmailDelivery.objects.count() == 3


@pytest.mark.django_db
def test_recovery_does_not_issue_links_for_inactive_or_unreachable_accounts(client, settings):
    settings.WEB_PUSH_ENABLED = False
    UserFactory(username="inactive", email="inactive@example.test", is_active=False)
    UserFactory(username="unreachable", email="")
    participant = ParticipantFactory(email="archived@example.test", archived_at=timezone.now())

    for identifier in ["inactive@example.test", "unreachable", participant.email]:
        client.post(reverse("account-recovery-request"), {"identifier": identifier})
    client.post(reverse("kiosk-pin-recovery-request"), {"email": participant.email})

    assert AccountRecoveryToken.objects.count() == 0
    assert EmailDelivery.objects.count() == 0
    assert PushMessage.objects.count() == 0


@pytest.mark.django_db
def test_push_only_account_can_recover_without_email(client, settings):
    settings.WEB_PUSH_ENABLED = True
    user = UserFactory(username="push-only", email="")
    PushSubscription.objects.create(
        user=user,
        endpoint="https://push.example.test/push-only-recovery",
        p256dh="key",
        auth="auth",
        categories=[],
    )

    client.post(reverse("account-recovery-request"), {"identifier": user.username})

    recovery = AccountRecoveryToken.objects.get()
    message = PushMessage.objects.get()
    assert recovery.expires_at is None
    with patch("billing.notifications.webpush") as webpush:
        assert send_due_push_messages().sent == 1
    raw_token = json.loads(webpush.call_args.kwargs["data"])["url"].rstrip("/").rsplit("/", maxsplit=1)[-1]
    recovery.refresh_from_db()
    message.refresh_from_db()
    assert recovery.token_digest == hashlib.sha256(raw_token.encode()).hexdigest()
    assert raw_token not in message.target_url
    assert EmailDelivery.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("owner_kind", ["participant", "companion"])
def test_kiosk_push_only_account_can_start_recovery_with_kiosk_identifier(kiosk_client, settings, owner_kind):
    settings.WEB_PUSH_ENABLED = True
    participant = ParticipantFactory(email="")
    if owner_kind == "participant":
        owner = participant
        identifier = f"participant-{owner.pk}"
    else:
        owner = ParticipantFamilyMemberFactory(
            guardian=participant,
            email="",
            role=ParticipantFamilyMember.Role.COMPANION,
        )
        identifier = f"family-{owner.pk}"
    PushSubscription.objects.create(
        **({"participant": participant} if owner_kind == "participant" else {"family_member": owner}),
        endpoint=f"https://push.example.test/{owner_kind}-recovery",
        p256dh="key",
        auth="auth",
        categories=[],
    )

    response = kiosk_client.post(reverse("kiosk-pin-recovery-request"), {"participant": identifier})

    assert response.status_code == 302
    assert response.url == reverse("account-recovery-sent")
    assert AccountRecoveryToken.objects.filter(
        **({"participant": owner.pk} if owner_kind == "participant" else {"family_member": owner.pk})
    ).exists()
    assert PushMessage.objects.count() == 1
    assert EmailDelivery.objects.count() == 0


@pytest.mark.django_db
def test_kiosk_recovery_unknown_identifier_does_not_disclose_or_deliver(kiosk_client, settings):
    settings.WEB_PUSH_ENABLED = True

    response = kiosk_client.post(
        reverse("kiosk-pin-recovery-request"),
        {"participant": "participant-999999"},
        follow=True,
    )

    assert response.status_code == 200
    assert "Falls ein aktives Konto passt" in response.content.decode()
    assert AccountRecoveryToken.objects.count() == 0
    assert PushMessage.objects.count() == 0
    assert EmailDelivery.objects.count() == 0


@pytest.mark.django_db
def test_kiosk_recovery_identifier_prefix_prevents_participant_family_collision(kiosk_client, settings):
    settings.WEB_PUSH_ENABLED = True
    participant = ParticipantFactory(email="")
    companion = ParticipantFamilyMemberFactory(
        guardian=participant,
        email="",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    PushSubscription.objects.create(
        family_member=companion,
        endpoint="https://push.example.test/prefix-recovery",
        p256dh="key",
        auth="auth",
        categories=[],
    )

    kiosk_client.post(reverse("kiosk-pin-recovery-request"), {"participant": f"family-{participant.pk}"})

    recovery = AccountRecoveryToken.objects.get()
    assert recovery.family_member_id == companion.pk
    assert recovery.participant_id is None
    assert PushMessage.objects.count() == 1


@pytest.mark.django_db
def test_invalid_push_endpoint_does_not_activate_recovery_token(client, settings):
    settings.WEB_PUSH_ENABLED = True
    user = UserFactory(username="invalid-push", email="")
    subscription = PushSubscription.objects.create(
        user=user,
        endpoint="https://push.example.test/initially-valid",
        p256dh="key",
        auth="auth",
        categories=[],
    )
    PushSubscription.objects.filter(pk=subscription.pk).update(endpoint="http://push.example.test/insecure")
    client.post(reverse("account-recovery-request"), {"identifier": user.username})

    result = send_due_push_messages()

    recovery = AccountRecoveryToken.objects.get()
    assert result.failed == 1
    assert recovery.token_digest is None
    assert recovery.expires_at is None


@pytest.mark.django_db
def test_requesting_a_new_link_invalidates_the_previous_link(client):
    user = UserFactory(email="renew@example.test")
    client.post(reverse("account-recovery-request"), {"identifier": user.email})
    _send_recovery_emails()
    first_path = urlsplit(mail.outbox[-1].body.splitlines()[-1]).path

    client.post(reverse("account-recovery-request"), {"identifier": user.email})
    _send_recovery_emails()
    second_path = urlsplit(mail.outbox[-1].body.splitlines()[-1]).path

    assert first_path != second_path
    assert client.get(first_path).status_code == 400
    assert client.get(second_path).status_code == 200


@pytest.mark.django_db
def test_recovery_link_is_invalid_after_the_credential_changes(client):
    user = UserFactory(email="changed@example.test", password="old-password")
    client.post(reverse("account-recovery-request"), {"identifier": user.email})
    _send_recovery_emails()
    path = urlsplit(mail.outbox[-1].body.splitlines()[-1]).path

    user.set_password("changed-outside-recovery")
    user.save(update_fields=["password"])

    assert client.get(path).status_code == 400


@pytest.mark.django_db
def test_recovery_confirm_marks_all_new_credentials_as_sensitive(monkeypatch):
    from billing import account_recovery

    captured_request = None

    def capture_invalid(request):
        nonlocal captured_request
        captured_request = request
        return object()

    monkeypatch.setattr(account_recovery, "find_valid_account_recovery", lambda token: None)
    monkeypatch.setattr(account_recovery, "_invalid_token_response", capture_invalid)
    request = RequestFactory().post(
        "/account/recovery/token/",
        {"new_password1": "secret", "new_password2": "secret", "pin": "1234", "pin_repeat": "1234"},
    )

    account_recovery.account_recovery_confirm(request, "token")

    assert captured_request is not None
    assert set(captured_request.sensitive_post_parameters) == {
        "new_password1",
        "new_password2",
        "pin",
        "pin_repeat",
    }


@pytest.mark.django_db
@pytest.mark.parametrize("owner_kind", ["admin", "participant", "companion"])
def test_recovery_email_is_suppressed_when_owner_address_changes_before_delivery(owner_kind):
    if owner_kind == "admin":
        owner = SuperUserFactory(email="initial@example.test")
        kind = AccountRecoveryToken.Kind.USER_PASSWORD
    elif owner_kind == "participant":
        owner = ParticipantFactory(email="initial@example.test")
        kind = AccountRecoveryToken.Kind.PARTICIPANT_PIN
    else:
        owner = ParticipantFamilyMemberFactory(
            guardian=ParticipantFactory(email="guardian@example.test"),
            email="initial@example.test",
            role=ParticipantFamilyMember.Role.COMPANION,
        )
        kind = AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN

    recovery = create_account_recovery_token(kind=kind, owner=owner)
    queue_account_recovery_email(
        recipient_email=owner.email,
        recipient_name=owner.full_name if hasattr(owner, "full_name") else owner.get_full_name(),
        subject="Passwort zurücksetzen",
        body="ACCOUNT_RECOVERY_TOKEN",
        account_recovery=recovery,
    )
    owner.email = "changed@example.test"
    owner.save(update_fields=["email"])

    result = _send_recovery_emails(expected_failed=1)

    delivery = EmailDelivery.objects.get()
    recovery.refresh_from_db()
    assert result.failed == 1
    assert delivery.status == EmailDelivery.Status.FAILED
    assert delivery.last_error_code == "recovery_unavailable"
    assert recovery.token_digest is None
    assert recovery.expires_at is None
    assert mail.outbox == []


@pytest.mark.django_db
@pytest.mark.parametrize("owner_kind", ["participant", "companion"])
def test_recovery_activation_locks_the_actual_pin_row(monkeypatch, owner_kind):
    participant = ParticipantFactory(email="owner@example.test")
    if owner_kind == "participant":
        owner = participant
        kind = AccountRecoveryToken.Kind.PARTICIPANT_PIN
        expected_model = ParticipantPin
    else:
        owner = ParticipantFamilyMemberFactory(
            guardian=participant,
            email="companion@example.test",
            role=ParticipantFamilyMember.Role.COMPANION,
        )
        kind = AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN
        expected_model = ParticipantFamilyMemberPin
    recovery = create_account_recovery_token(kind=kind, owner=owner)
    locked_models = []
    real_fetch_all = QuerySet._fetch_all

    def capture_locked_model(queryset):
        if queryset._result_cache is None and queryset.query.select_for_update:
            locked_models.append(queryset.model)
        real_fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", capture_locked_model)

    raw_token = activate_account_recovery_token(recovery.pk)

    assert raw_token is not None
    assert expected_model in locked_models


@pytest.mark.django_db
def test_companion_can_recover_own_pin_and_message_identifies_account(kiosk_client):
    guardian = ParticipantFactory(email="shared@example.test")
    companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        first_name="Grace",
        last_name="Hopper",
        email="shared@example.test",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    companion.pin.set_pin("2468")
    companion.pin.save()

    kiosk_client.post(reverse("kiosk-pin-recovery-request"), {"email": companion.email})

    assert EmailDelivery.objects.count() == 2
    queued_bodies = " ".join(EmailDelivery.objects.values_list("body_text", flat=True))
    assert all(name in queued_bodies for name in [guardian.full_name, companion.full_name])
    _send_recovery_emails()
    companion_message = next(message for message in mail.outbox if companion.full_name in message.body)
    path = urlsplit(companion_message.body.splitlines()[-1]).path
    response = kiosk_client.post(path, {"pin": "8642", "pin_repeat": "8642"}, follow=True)

    assert response.status_code == 200
    companion.pin.refresh_from_db()
    assert companion.pin.check_pin("8642") is True
    guardian.pin.refresh_from_db()
    assert guardian.pin.check_pin("8642") is False


@pytest.mark.django_db
def test_email_settings_excludes_system_recovery_batches(client):
    admin = SuperUserFactory(email="admin@example.test")
    client.post(reverse("account-recovery-request"), {"identifier": admin.email})
    recovery_batch = EmailBatch.objects.get(kind=EmailBatch.Kind.ACCOUNT_RECOVERY)
    client.force_login(admin)

    response = client.get(reverse("email-settings"))

    assert response.status_code == 200
    assert recovery_batch not in list(response.context["recent_batches"])
    assert client.get(reverse("email-batch-detail", args=[recovery_batch.pk])).status_code == 404
    delivery = recovery_batch.deliveries.get()
    assert client.post(reverse("email-delivery-retry", args=[delivery.pk])).status_code == 404
