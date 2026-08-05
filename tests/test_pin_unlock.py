from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from tests.factories import ParticipantFactory, SuperUserFactory, UserFactory


@pytest.mark.django_db
def test_participant_pin_unlock_pin_method():
    participant = ParticipantFactory()
    pin = participant.pin
    pin.pin_hash = "hashed_pin"
    pin.failed_attempts = 3
    pin.locked_until = timezone.now() + timedelta(minutes=10)
    pin.save()
    assert pin.is_locked

    pin.unlock_pin()
    pin.save()

    pin.refresh_from_db()
    assert not pin.is_locked
    assert pin.locked_until is None
    assert pin.failed_attempts == 0


@pytest.mark.django_db
def test_pin_unlock_view_as_admin(client):
    admin = SuperUserFactory()
    participant = ParticipantFactory()
    pin = participant.pin
    pin.pin_hash = "hashed_pin"
    pin.failed_attempts = 5
    pin.locked_until = timezone.now() + timedelta(minutes=10)
    pin.save()

    client.force_login(admin)
    url = reverse("pin-unlock", kwargs={"participant_id": participant.pk})
    response = client.post(url)

    assert response.status_code == 302
    assert response.url == reverse("participant-detail", kwargs={"participant_id": participant.pk})

    pin.refresh_from_db()
    assert not pin.is_locked
    assert pin.locked_until is None
    assert pin.failed_attempts == 0


@pytest.mark.django_db
def test_pin_unlock_view_requires_admin(client):
    user = UserFactory()
    participant = ParticipantFactory()
    pin = participant.pin
    pin.pin_hash = "hashed_pin"
    pin.failed_attempts = 5
    pin.locked_until = timezone.now() + timedelta(minutes=10)
    pin.save()

    client.force_login(user)
    url = reverse("pin-unlock", kwargs={"participant_id": participant.pk})
    response = client.post(url)

    # non-staff/non-admin user should not be allowed
    assert response.status_code in (302, 403)


@pytest.mark.django_db
def test_participant_detail_shows_unlock_button_when_locked(client):
    admin = SuperUserFactory()
    participant = ParticipantFactory()
    pin = participant.pin
    pin.pin_hash = "hashed_pin"
    pin.failed_attempts = 5
    pin.locked_until = timezone.now() + timedelta(minutes=10)
    pin.save()

    client.force_login(admin)
    url = reverse("participant-detail", kwargs={"participant_id": participant.pk})
    response = client.get(url)

    assert response.status_code == 200
    assert "Timeout zurücksetzen" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_participant_pin_unlock_when_not_locked():
    participant = ParticipantFactory()
    pin = participant.pin
    pin.failed_attempts = 2
    pin.locked_until = None
    pin.save()

    assert not pin.is_locked
    pin.unlock_pin()
    pin.save()

    pin.refresh_from_db()
    assert pin.failed_attempts == 0
    assert pin.locked_until is None


@pytest.mark.django_db
def test_participant_family_member_pin_unlock_pin_method():
    from billing.models import ParticipantFamilyMember, ParticipantFamilyMemberPin

    participant = ParticipantFactory()
    family_member = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Kind",
        last_name="Muster",
    )
    pin, _ = ParticipantFamilyMemberPin.objects.get_or_create(family_member=family_member)
    pin.failed_attempts = 4
    pin.locked_until = timezone.now() + timedelta(minutes=5)
    pin.save()

    assert pin.is_locked
    pin.unlock_pin()
    pin.save()

    pin.refresh_from_db()
    assert not pin.is_locked
    assert pin.locked_until is None
    assert pin.failed_attempts == 0


@pytest.mark.django_db
def test_admin_user_login_lockout_unlock(client):
    from billing.kiosk_security import check_login_rate_limit, consume_login_failure

    target_user = UserFactory(username="target_admin")
    admin = SuperUserFactory()

    req = client.get("/").wsgi_request
    for _ in range(5):
        consume_login_failure(req, username="target_admin")

    assert not check_login_rate_limit(req, username="target_admin")

    client.force_login(admin)
    url = reverse("user-unlock", kwargs={"user_id": target_user.pk})
    response = client.post(url)

    assert response.status_code == 302
    assert response.url == reverse("user-list")

    req_other_ip = client.get("/", REMOTE_ADDR="10.0.0.99").wsgi_request
    assert check_login_rate_limit(req_other_ip, username="target_admin")


@pytest.mark.django_db
def test_user_list_shows_unlock_button_when_user_locked_out(client):
    from billing.kiosk_security import consume_login_failure

    _target_user = UserFactory(username="locked_admin")
    admin = SuperUserFactory()

    req = client.get("/").wsgi_request
    for _ in range(5):
        consume_login_failure(req, username="locked_admin")

    client.force_login(admin)
    url = reverse("user-list")
    response = client.get(url)

    assert response.status_code == 200
    assert "Timeout zurücksetzen" in response.content.decode("utf-8")
