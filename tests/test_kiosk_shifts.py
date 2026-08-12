import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

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
def test_kiosk_can_filter_open_shifts_by_date_and_name(logged_in_kiosk_client, active_camp):
    matching_shift = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    Shift.objects.create(
        camp=active_camp,
        name="Aufsicht",
        date=datetime.date.today() + datetime.timedelta(days=3),
        required_slots=1,
    )

    response = logged_in_kiosk_client.get(
        reverse("kiosk-shifts"),
        {"date": matching_shift.date.isoformat(), "name": "küche"},
    )

    assert response.status_code == 200
    assert [shift.pk for shift in response.context["open_shifts"]] == [matching_shift.pk]
    assert response.context["shift_date_filter"] == matching_shift.date.isoformat()
    assert response.context["shift_name_filter"] == "küche"


@pytest.mark.django_db
def test_kiosk_bulk_selection_excludes_full_shifts_without_exchange_offer(logged_in_kiosk_client, active_camp):
    available = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    full = Shift.objects.create(
        camp=active_camp,
        name="Aufsicht",
        date=datetime.date.today() + datetime.timedelta(days=3),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User")
    ShiftAssignment.objects.create(shift=full, participant=other)

    response = logged_in_kiosk_client.get(reverse("kiosk-shifts"))

    content = response.content.decode()
    assert f'name="shift_ids" value="{available.pk}"' in content
    assert f'name="shift_ids" value="{full.pk}"' not in content
    assert full.name in content


@pytest.mark.django_db
def test_kiosk_full_shift_with_exchange_offer_stays_available_for_takeover(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Aufsicht",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User")
    ShiftAssignment.objects.create(shift=shift, participant=other, offered_for_exchange=True)

    response = logged_in_kiosk_client.get(reverse("kiosk-shifts"))

    content = response.content.decode()
    assert f'name="shift_ids" value="{shift.pk}"' not in content
    assert "Dienst übernehmen" in content


@pytest.mark.django_db
def test_kiosk_shift_filter_keeps_last_booked_service_selected(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    filter_data = {"date": shift.date.isoformat(), "name": shift.name}

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "signup", "shift_id": shift.pk, **filter_data},
        follow=True,
    )

    assert response.status_code == 200
    assert response.context["shift_name_choices"] == [shift.name]
    assert f'<option value="{shift.name}" selected>' in response.content.decode()


@pytest.mark.django_db
def test_kiosk_shift_filters_use_german_weekday_and_existing_service_choices(logged_in_kiosk_client, active_camp):
    monday = datetime.date.today() + datetime.timedelta(days=(7 - datetime.date.today().weekday()) % 7)
    kitchen_shift = Shift.objects.create(camp=active_camp, name="Küchendienst", date=monday, required_slots=1)
    Shift.objects.create(camp=active_camp, name="Aufsicht", date=monday, required_slots=1)

    response = logged_in_kiosk_client.get(reverse("kiosk-shifts"), {"date": monday.isoformat(), "name": "Küchendienst"})

    assert response.status_code == 200
    assert f"Montag, {monday:%d.%m.%Y}" in response.content.decode()
    assert response.context["shift_name_choices"] == ["Aufsicht", "Küchendienst"]
    assert [shift.pk for shift in response.context["open_shifts"]] == [kitchen_shift.pk]


@pytest.mark.django_db
def test_kiosk_single_signup_preserves_combined_filters(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    filter_data = {"date": shift.date.isoformat(), "name": shift.name}

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "signup", "shift_id": shift.pk, **filter_data},
    )

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('kiosk-shifts')}?date={shift.date.isoformat()}&name=K%C3%BCchendienst"


@pytest.mark.django_db
def test_kiosk_bulk_signup_books_all_selected_shifts_atomically(logged_in_kiosk_client, active_camp):
    shifts = [
        Shift.objects.create(
            camp=active_camp,
            name=name,
            date=datetime.date.today() + datetime.timedelta(days=offset),
            required_slots=1,
        )
        for name, offset in (("Küchendienst", 2), ("Aufsicht", 3))
    ]

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "bulk_signup", "shift_ids": [str(shift.pk) for shift in shifts]},
    )

    assert response.status_code == 302
    assert set(
        ShiftAssignment.objects.filter(participant=logged_in_kiosk_client.kiosk_user).values_list("shift_id", flat=True)
    ) == {shift.pk for shift in shifts}


@pytest.mark.django_db
@pytest.mark.parametrize("shift_ids", [[], ["not-an-id"], ["999999"]])
def test_kiosk_bulk_signup_rejects_empty_foreign_or_malformed_ids(logged_in_kiosk_client, active_camp, shift_ids):
    Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    payload = {"action": "bulk_signup", "shift_ids": shift_ids}
    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), payload)

    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_bulk_signup_rejects_duplicates_and_does_not_partially_book(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "bulk_signup", "shift_ids": [str(shift.pk), str(shift.pk)]},
    )

    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_bulk_signup_rejects_full_shift_without_partial_booking(logged_in_kiosk_client, active_camp):
    available = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    full = Shift.objects.create(
        camp=active_camp,
        name="Aufsicht",
        date=datetime.date.today() + datetime.timedelta(days=3),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User")
    ShiftAssignment.objects.create(shift=full, participant=other)

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "bulk_signup", "shift_ids": [str(available.pk), str(full.pk)]},
    )

    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_bulk_signup_rejects_shift_from_another_camp(logged_in_kiosk_client, active_camp):
    foreign_camp = Camp.objects.create(
        name="Foreign Camp",
        year=active_camp.year,
        starts_on=active_camp.starts_on,
        ends_on=active_camp.ends_on,
        is_active=True,
    )
    local_shift = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    foreign_shift = Shift.objects.create(
        camp=foreign_camp,
        name="Fremder Dienst",
        date=local_shift.date,
        required_slots=1,
    )

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "bulk_signup", "shift_ids": [str(local_shift.pk), str(foreign_shift.pk)]},
    )

    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_can_retract_own_shift_assignment_within_15_minutes(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    assignment = ShiftAssignment.objects.create(shift=shift, participant=logged_in_kiosk_client.kiosk_user)
    ShiftAssignment.objects.filter(pk=assignment.pk).update(created_at=timezone.now() - datetime.timedelta(minutes=14))

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "retract", "shift_id": shift.pk},
    )

    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(pk=assignment.pk).exists()


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
    assignment = ShiftAssignment.objects.create(shift=shift, participant=logged_in_kiosk_client.kiosk_user)
    ShiftAssignment.objects.filter(pk=assignment.pk).update(created_at=timezone.now() - datetime.timedelta(minutes=16))
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
