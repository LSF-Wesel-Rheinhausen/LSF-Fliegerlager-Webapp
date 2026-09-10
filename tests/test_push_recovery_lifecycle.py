"""Regression coverage for recovery push capabilities and credential rotations."""

from unittest.mock import patch

import pytest
from django.db.models import QuerySet
from django.urls import reverse

from billing.models import AccountRecoveryToken, ParticipantFamilyMember, PushSubscription
from billing.notifications import queue_account_recovery_push, send_due_push_messages
from billing.recovery_tokens import create_account_recovery_token, find_valid_account_recovery
from tests.factories import ParticipantFactory, UserFactory
from tests.kiosk_helpers import authenticate_kiosk_session


@pytest.mark.django_db
@pytest.mark.parametrize("revocation", ["deactivate", "unverify", "delete"])
def test_delivered_push_recovery_capability_requires_its_exact_subscription(settings, revocation):
    settings.WEB_PUSH_ENABLED = True
    user = UserFactory(password="old-password")
    target = PushSubscription.objects.create(
        user=user, endpoint="https://push.example.test/target", p256dh="key", auth="auth"
    )
    queue_account_recovery_push(
        user,
        kind=AccountRecoveryToken.Kind.USER_PASSWORD,
        title="Reset",
        body="Link",
        target_url="/account-recovery/ACCOUNT_RECOVERY_TOKEN/",
    )

    with patch("billing.notifications.webpush") as webpush:
        send_due_push_messages()
    payload = webpush.call_args_list[0].kwargs["data"]
    raw_token = payload.split('"url": "/account-recovery/')[1].split('/"')[0]
    token = AccountRecoveryToken.objects.get(token_digest__isnull=False)
    assert token.delivery_subscription_id == target.pk
    other = PushSubscription.objects.create(
        user=user, endpoint="https://push.example.test/other", p256dh="key", auth="auth"
    )

    if revocation == "deactivate":
        PushSubscription.objects.filter(pk=target.pk).update(is_active=False)
    elif revocation == "unverify":
        PushSubscription.objects.filter(pk=target.pk).update(identity_verified=False)
    else:
        target.delete()

    assert find_valid_account_recovery(raw_token) is None
    other.refresh_from_db()
    assert other.is_active is True


@pytest.mark.django_db
def test_admin_password_reset_revokes_only_the_reset_users_devices(client):
    admin = UserFactory(is_superuser=True)
    client.force_login(admin)
    target = UserFactory(password="old-password")
    own = PushSubscription.objects.create(
        user=target, endpoint="https://push.example.test/own", p256dh="key", auth="auth"
    )
    foreign = PushSubscription.objects.create(
        user=admin, endpoint="https://push.example.test/foreign", p256dh="key", auth="auth"
    )

    response = client.post(
        reverse("user-password-reset", args=[target.pk]),
        {"new_password1": "new-password", "new_password2": "new-password"},
    )

    assert response.status_code == 302
    own.refresh_from_db()
    foreign.refresh_from_db()
    assert own.is_active is False
    assert foreign.is_active is True


@pytest.mark.django_db
def test_credential_rotation_locks_owner_token_then_subscriptions(client, monkeypatch):
    admin = UserFactory(is_superuser=True)
    client.force_login(admin)
    target = UserFactory(password="old-password")
    create_account_recovery_token(kind=AccountRecoveryToken.Kind.USER_PASSWORD, owner=target)
    PushSubscription.objects.create(user=target, endpoint="https://push.example.test/own", p256dh="key", auth="auth")
    locked_models = []
    fetch_all = QuerySet._fetch_all

    def record_locks(queryset):
        if queryset._result_cache is None and queryset.query.select_for_update:
            locked_models.append(queryset.model.__name__)
        fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", record_locks)

    response = client.post(
        reverse("user-password-reset", args=[target.pk]),
        {"new_password1": "new-password", "new_password2": "new-password"},
    )

    assert response.status_code == 302
    assert locked_models.index("User") < locked_models.index("AccountRecoveryToken")
    assert locked_models.index("AccountRecoveryToken") < locked_models.index("PushSubscription")


@pytest.mark.django_db
def test_pin_set_revokes_participant_devices_only_after_an_established_pin(client):
    admin = UserFactory(is_superuser=True)
    client.force_login(admin)
    participant = ParticipantFactory()
    participant.pin.set_pin("2468")
    participant.pin.save()
    own = PushSubscription.objects.create(
        participant=participant, endpoint="https://push.example.test/own", p256dh="key", auth="auth"
    )

    response = client.post(reverse("pin-set", args=[participant.pk]), {"pin": "8642", "pin_repeat": "8642"})

    assert response.status_code == 302
    own.refresh_from_db()
    assert own.identity_verified is False


@pytest.mark.django_db
def test_pin_set_keeps_device_verified_for_first_provisioning(client):
    admin = UserFactory(is_superuser=True)
    client.force_login(admin)
    participant = ParticipantFactory()
    participant.pin.reset_pin()
    participant.pin.save()
    own = PushSubscription.objects.create(
        participant=participant, endpoint="https://push.example.test/own", p256dh="key", auth="auth"
    )

    response = client.post(reverse("pin-set", args=[participant.pk]), {"pin": "8642", "pin_repeat": "8642"})

    assert response.status_code == 302
    own.refresh_from_db()
    assert own.identity_verified is True


@pytest.mark.django_db
def test_admin_pin_reset_revokes_participant_devices(client):
    admin = UserFactory(is_superuser=True)
    client.force_login(admin)
    participant = ParticipantFactory()
    own = PushSubscription.objects.create(
        participant=participant, endpoint="https://push.example.test/own", p256dh="key", auth="auth"
    )

    response = client.post(reverse("pin-reset", args=[participant.pk]))

    assert response.status_code == 302
    own.refresh_from_db()
    assert own.identity_verified is False


@pytest.mark.django_db
@pytest.mark.parametrize("owner_kind", ["participant", "family_member"])
def test_kiosk_pin_change_revokes_the_authenticated_owners_devices(kiosk_client, owner_kind):
    participant = ParticipantFactory()
    participant.pin.set_pin("2468")
    participant.pin.save()
    family_member = None
    owner_kwargs = {"participant": participant}
    if owner_kind == "family_member":
        family_member = ParticipantFamilyMember.objects.create(
            guardian=participant,
            first_name="Grace",
            last_name="Hopper",
            role=ParticipantFamilyMember.Role.COMPANION,
        )
        family_member.pin.set_pin("2468")
        family_member.pin.save()
        owner_kwargs = {"family_member": family_member}
    own = PushSubscription.objects.create(
        **owner_kwargs,
        endpoint=f"https://push.example.test/{owner_kind}",
        p256dh="key",
        auth="auth",
    )
    session = kiosk_client.session
    authenticate_kiosk_session(session, participant, family_member=family_member)
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "pin_change",
            "pin-current_pin": "2468",
            "pin-pin": "8642",
            "pin-pin_repeat": "8642",
        },
    )

    assert response.status_code == 302
    own.refresh_from_db()
    assert own.identity_verified is False


@pytest.mark.django_db
def test_guardian_pin_rotation_revokes_companion_devices(kiosk_client):
    participant = ParticipantFactory()
    family_member = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    family_member.pin.set_pin("2468")
    family_member.pin.save()
    own = PushSubscription.objects.create(
        family_member=family_member,
        endpoint="https://push.example.test/family-member",
        p256dh="key",
        auth="auth",
    )
    session = kiosk_client.session
    authenticate_kiosk_session(session, participant)
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_pin_set",
            "family_member_id": family_member.pk,
            "family-pin": "8642",
            "family-pin_repeat": "8642",
        },
    )

    assert response.status_code == 302
    own.refresh_from_db()
    assert own.identity_verified is False


@pytest.mark.django_db
def test_recovery_push_activation_locks_owner_token_then_subscription(monkeypatch, settings):
    settings.WEB_PUSH_ENABLED = True
    user = UserFactory(password="old-password")
    PushSubscription.objects.create(user=user, endpoint="https://push.example.test/owner", p256dh="key", auth="auth")
    queue_account_recovery_push(
        user,
        kind=AccountRecoveryToken.Kind.USER_PASSWORD,
        title="Reset",
        body="Link",
        target_url="/account-recovery/ACCOUNT_RECOVERY_TOKEN/",
    )
    locked_models = []
    fetch_all = QuerySet._fetch_all

    def record_locks(queryset):
        if queryset._result_cache is None and queryset.query.select_for_update:
            locked_models.append(queryset.model.__name__)
        fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", record_locks)
    with patch("billing.notifications.webpush"):
        send_due_push_messages()

    assert locked_models.index("User") < locked_models.index("AccountRecoveryToken")
    assert locked_models.index("AccountRecoveryToken") < locked_models.index("PushSubscription")


@pytest.mark.django_db
def test_invalid_recovery_endpoint_locks_owner_before_revoking_subscription(monkeypatch, settings):
    settings.WEB_PUSH_ENABLED = True
    user = UserFactory(password="old-password")
    subscription = PushSubscription.objects.create(
        user=user, endpoint="https://push.example.test/owner", p256dh="key", auth="auth"
    )
    PushSubscription.objects.filter(pk=subscription.pk).update(endpoint="http://invalid.test/owner")
    queue_account_recovery_push(
        user,
        kind=AccountRecoveryToken.Kind.USER_PASSWORD,
        title="Reset",
        body="Link",
        target_url="/account-recovery/ACCOUNT_RECOVERY_TOKEN/",
    )
    events = []
    fetch_all = QuerySet._fetch_all
    update = QuerySet.update

    def record_locks(queryset):
        if queryset._result_cache is None and queryset.query.select_for_update:
            events.append(f"lock:{queryset.model.__name__}")
        fetch_all(queryset)

    def record_updates(queryset, **kwargs):
        if queryset.model is PushSubscription:
            events.append("update:PushSubscription")
        return update(queryset, **kwargs)

    monkeypatch.setattr(QuerySet, "_fetch_all", record_locks)
    monkeypatch.setattr(QuerySet, "update", record_updates)

    send_due_push_messages()

    assert events.index("lock:User") < events.index("update:PushSubscription")


@pytest.mark.django_db
def test_recovery_push_rechecks_endpoint_after_locking_subscription(settings):
    settings.WEB_PUSH_ENABLED = True
    user = UserFactory(password="old-password")
    subscription = PushSubscription.objects.create(
        user=user, endpoint="https://push.example.test/owner", p256dh="key", auth="auth"
    )
    queue_account_recovery_push(
        user,
        kind=AccountRecoveryToken.Kind.USER_PASSWORD,
        title="Reset",
        body="Link",
        target_url="/account-recovery/ACCOUNT_RECOVERY_TOKEN/",
    )

    with (
        patch("billing.notifications.is_allowed_push_endpoint", return_value=True),
        patch("billing.recovery_tokens.is_allowed_push_endpoint", return_value=False),
        patch("billing.notifications.webpush") as webpush,
    ):
        result = send_due_push_messages()

    assert result.failed == 1
    webpush.assert_not_called()
    subscription.refresh_from_db()
    assert subscription.is_active is False
