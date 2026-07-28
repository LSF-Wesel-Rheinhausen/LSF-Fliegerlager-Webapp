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
def logged_in_kiosk_client(kiosk_client, active_camp):
    p = Participant.objects.create(camp=active_camp, first_name="Kiosk", last_name="User")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = p.pk
    session.save()
    kiosk_client.kiosk_user = p
    return kiosk_client


@pytest.fixture
def pre_camp_kiosk_client(kiosk_client):
    camp = Camp.objects.create(
        name="Future Camp",
        year=datetime.date.today().year + 1,
        starts_on=datetime.date.today() + datetime.timedelta(days=7),
        ends_on=datetime.date.today() + datetime.timedelta(days=14),
        is_active=True,
    )
    participant = Participant.objects.create(camp=camp, first_name="Kiosk", last_name="User")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    kiosk_client.kiosk_user = participant
    return kiosk_client


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "home_route_name"),
    [("kiosk-shifts", "kiosk-home"), ("central-kiosk-shifts", "central-kiosk-home")],
)
def test_pre_camp_kiosk_shift_pages_redirect_home(pre_camp_kiosk_client, route_name, home_route_name):
    response = pre_camp_kiosk_client.get(reverse(route_name))

    assert response.status_code == 302
    assert response.url == reverse(home_route_name)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "home_route_name"),
    [("kiosk-shifts", "kiosk-home"), ("central-kiosk-shifts", "central-kiosk-home")],
)
def test_pre_camp_kiosk_shift_posts_cannot_create_assignments(pre_camp_kiosk_client, route_name, home_route_name):
    participant = pre_camp_kiosk_client.kiosk_user
    shift = Shift.objects.create(
        camp=participant.camp,
        name="Future Shift",
        date=participant.camp.starts_on,
        required_slots=1,
    )

    response = pre_camp_kiosk_client.post(
        reverse(route_name),
        {"action": "signup", "shift_id": shift.pk},
    )

    assert response.status_code == 302
    assert response.url == reverse(home_route_name)
    assert not ShiftAssignment.objects.filter(shift=shift, participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_can_signup_for_shift(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})
    assert response.status_code == 302
    assert ShiftAssignment.objects.filter(shift=shift, participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_private_kiosk_shifts_context_disables_autologout(logged_in_kiosk_client, active_camp):
    response = logged_in_kiosk_client.get(reverse("kiosk-shifts"))
    assert response.status_code == 200
    assert response.context["kiosk_autologout"] is False


@pytest.mark.django_db
def test_kiosk_cannot_signup_for_full_shift(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User")
    ShiftAssignment.objects.create(shift=shift, participant=other)

    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})
    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(shift=shift, participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_cannot_retract(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    ShiftAssignment.objects.create(shift=shift, participant=logged_in_kiosk_client.kiosk_user)
    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "retract", "shift_id": shift.pk})
    assert response.status_code == 302
    assert ShiftAssignment.objects.filter(shift=shift, participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_can_offer_and_revoke_shift(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today(),
        required_slots=1,
    )
    assignment = ShiftAssignment.objects.create(shift=shift, participant=logged_in_kiosk_client.kiosk_user)

    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "offer", "shift_id": shift.pk})
    assert response.status_code == 302
    assignment.refresh_from_db()
    assert assignment.offered_for_exchange is True

    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "revoke_offer", "shift_id": shift.pk})
    assert response.status_code == 302
    assignment.refresh_from_db()
    assert assignment.offered_for_exchange is False


@pytest.mark.django_db
def test_kiosk_can_takeover_offered_shift(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today(),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User", status="active")
    ShiftAssignment.objects.create(shift=shift, participant=other, offered_for_exchange=True)

    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})
    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(shift=shift, participant=other).exists()
    assert ShiftAssignment.objects.filter(shift=shift, participant=logged_in_kiosk_client.kiosk_user).exists()
