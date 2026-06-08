import datetime

import pytest
from django.urls import reverse

from billing.models import Camp, Participant, Shift, ShiftAssignment
from billing.views import KIOSK_PARTICIPANT_SESSION_KEY


@pytest.fixture
def active_camp(db):
    return Camp.objects.create(
        name="Test Camp",
        year=datetime.date.today().year,
        starts_on=datetime.date.today() - datetime.timedelta(days=1),
        ends_on=datetime.date.today() + datetime.timedelta(days=10),
        is_active=True,
    )


@pytest.fixture
def kiosk_client(client, active_camp):
    p = Participant.objects.create(camp=active_camp, first_name="Kiosk", last_name="User")
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = p.pk
    session.save()
    client.kiosk_user = p
    return client


@pytest.mark.django_db
def test_kiosk_can_signup_for_shift(kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})
    assert response.status_code == 302
    assert ShiftAssignment.objects.filter(shift=shift, participant=kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_shifts_context_has_autologout(kiosk_client, active_camp):
    response = kiosk_client.get(reverse("kiosk-shifts"))
    assert response.status_code == 200
    assert response.context["kiosk_autologout"] is True


@pytest.mark.django_db
def test_kiosk_cannot_signup_for_full_shift(kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User")
    ShiftAssignment.objects.create(shift=shift, participant=other)

    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})
    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(shift=shift, participant=kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_can_retract_from_future_shift(kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    ShiftAssignment.objects.create(shift=shift, participant=kiosk_client.kiosk_user)
    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "retract", "shift_id": shift.pk})
    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(shift=shift, participant=kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_cannot_retract_same_day(kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today(),
        required_slots=1,
    )
    ShiftAssignment.objects.create(shift=shift, participant=kiosk_client.kiosk_user)
    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "retract", "shift_id": shift.pk})
    assert response.status_code == 302
    assert ShiftAssignment.objects.filter(shift=shift, participant=kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_can_offer_and_revoke_shift(kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today(),
        required_slots=1,
    )
    assignment = ShiftAssignment.objects.create(shift=shift, participant=kiosk_client.kiosk_user)

    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "offer", "shift_id": shift.pk})
    assert response.status_code == 302
    assignment.refresh_from_db()
    assert assignment.offered_for_exchange is True

    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "revoke_offer", "shift_id": shift.pk})
    assert response.status_code == 302
    assignment.refresh_from_db()
    assert assignment.offered_for_exchange is False


@pytest.mark.django_db
def test_kiosk_can_takeover_offered_shift(kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today(),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User", status="active")
    assignment = ShiftAssignment.objects.create(shift=shift, participant=other, offered_for_exchange=True)

    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})
    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(shift=shift, participant=other).exists()
    assert ShiftAssignment.objects.filter(shift=shift, participant=kiosk_client.kiosk_user).exists()
