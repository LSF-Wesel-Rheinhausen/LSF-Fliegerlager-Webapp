from urllib.parse import urlsplit

import pytest
from django.contrib.auth import authenticate
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from billing.kiosk_security import consume_login_failure, is_login_locked_out
from billing.models import AccountRecoveryToken, EmailDelivery, PushMessage, PushSubscription
from tests.factories import ParticipantFactory, SuperUserFactory, UserFactory


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
    assert "/account/recovery/confirm/" in delivery.body_text
    message = PushMessage.objects.get(subscription=subscription)
    assert message.category == "account_security"
    assert message.title == "Passwort zurücksetzen"
    assert message.target_url.startswith("/account/recovery/confirm/")
    assert "password" not in message.target_url.casefold()

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
    client.post(reverse("account-recovery-request"), {"identifier": user.username}, follow=True)
    path = urlsplit(EmailDelivery.objects.get().body_text.splitlines()[-1]).path

    reset_page = client.get(path)
    assert reset_page.status_code == 200
    assert reset_page["Cache-Control"] == "no-store"
    assert reset_page["Referrer-Policy"] == "no-referrer"
    assert path.encode() not in reset_page.content
    reset_response = client.post(
        path,
        {"new_password1": "A-secure-new-password-601", "new_password2": "A-secure-new-password-601"},
        follow=True,
    )

    assert reset_response.status_code == 200
    assert "Passwort wurde geändert" in reset_response.content.decode()
    assert authenticate(username=user.username, password="A-secure-new-password-601") == user
    assert is_login_locked_out(user.username) is False
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
    delivery = EmailDelivery.objects.get()
    path = urlsplit(delivery.body_text.splitlines()[-1]).path
    message = PushMessage.objects.get(subscription=subscription)
    assert message.title == "PIN zurücksetzen"
    assert message.target_url == path

    reset_response = kiosk_client.post(path, {"pin": "8642", "pin_repeat": "8642"}, follow=True)

    assert reset_response.status_code == 200
    assert "PIN wurde geändert" in reset_response.content.decode()
    participant.pin.refresh_from_db()
    assert participant.pin.check_pin("8642") is True
    assert kiosk_client.get(path).status_code == 400


@pytest.mark.django_db
def test_recovery_rejects_expired_tokens_without_changing_credentials(client, settings):
    settings.ACCOUNT_RECOVERY_TIMEOUT_SECONDS = 60
    user = UserFactory(email="expired@example.test", password="old-password")
    requested_at = timezone.now()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("billing.account_recovery.timezone.now", lambda: requested_at)
        client.post(reverse("account-recovery-request"), {"identifier": user.email})
    path = urlsplit(EmailDelivery.objects.get().body_text.splitlines()[-1]).path

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "billing.account_recovery.timezone.now",
            lambda: requested_at + timezone.timedelta(seconds=61),
        )
        response = client.post(
            path,
            {"new_password1": "Another-secure-password-601", "new_password2": "Another-secure-password-601"},
        )

    assert response.status_code == 400
    assert authenticate(username=user.username, password="old-password") == user


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
    raw_token = message.target_url.rstrip("/").rsplit("/", maxsplit=1)[-1]
    assert recovery.token_digest != raw_token
    assert EmailDelivery.objects.count() == 0


@pytest.mark.django_db
def test_requesting_a_new_link_invalidates_the_previous_link(client):
    user = UserFactory(email="renew@example.test")
    client.post(reverse("account-recovery-request"), {"identifier": user.email})
    first_path = urlsplit(EmailDelivery.objects.get().body_text.splitlines()[-1]).path

    client.post(reverse("account-recovery-request"), {"identifier": user.email})
    second_path = urlsplit(EmailDelivery.objects.latest("pk").body_text.splitlines()[-1]).path

    assert first_path != second_path
    assert client.get(first_path).status_code == 400
    assert client.get(second_path).status_code == 200
