from datetime import date, datetime, time

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from billing.kiosk_access import KIOSK_PARTICIPANT_SESSION_KEY
from billing.models import MealBookingOverride, MealSignup
from billing.permissions import HUEBERS_GROUP
from billing.services import meal_booking_state
from tests.factories import CampFactory, GroupFactory, ParticipantFactory, UserFactory


@pytest.mark.django_db
def test_meal_manager_can_reopen_tomorrow_after_cutoff_per_meal(kiosk_client, monkeypatch):
    """Reproduce issue #416: cutoff closure must be overridable per meal slot."""
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 12, 1))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 2),
        meal_booking_cutoff_time=time(12, 0),
    )
    participant = ParticipantFactory(camp=camp)
    manager = UserFactory()
    manager.groups.add(GroupFactory(name=HUEBERS_GROUP))
    manager_client = kiosk_client.__class__()
    manager_client.force_login(manager)
    response = manager_client.post(
        reverse("meal-booking-override", args=[camp.pk]),
        {
            "meal_date": "2026-07-02",
            "meal": MealSignup.Meal.DINNER,
            "state": MealBookingOverride.State.OPEN,
        },
    )
    assert response.status_code == 302
    override = MealBookingOverride.objects.get(camp=camp)

    assert override.changed_by == manager
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    response = kiosk_client.get(reverse("kiosk-home"))
    assert response.status_code == 200
    dinner_day = next(day for day in response.context["dinner_calendar_days"] if day["date"] == date(2026, 7, 2))
    assert dinner_day["locked"] is False
    assert dinner_day["booking_state"] == "manual_open"


@pytest.mark.django_db
def test_manual_closed_dinner_is_independent_by_camp(client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 12, 1))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: fixed_now.date())
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 2), meal_booking_cutoff_time=time(12, 0))
    other_camp = CampFactory(name="Anderes Lager", starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 2))
    manager = UserFactory()
    manager.groups.add(GroupFactory(name=HUEBERS_GROUP))
    client.force_login(manager)

    response = client.post(
        reverse("meal-booking-override", args=[camp.pk]),
        {"meal_date": "2026-07-02", "meal": "dinner", "state": "closed"},
    )

    assert response.status_code == 302
    assert MealBookingOverride.objects.filter(camp=camp, meal="dinner", state="closed").exists()
    assert MealBookingOverride.objects.filter(camp=other_camp).exists() is False


@pytest.mark.django_db
@pytest.mark.parametrize("meal_date", [date(2026, 7, 1), date(2026, 7, 2)])
def test_stale_breakfast_closed_override_is_ignored_for_today_and_future(meal_date, monkeypatch):
    today = date(2026, 7, 1)
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: today)
    camp = CampFactory(starts_on=today, ends_on=date(2026, 7, 2))
    MealBookingOverride.objects.create(
        camp=camp,
        meal_date=meal_date,
        meal=MealSignup.Meal.BREAKFAST,
        state=MealBookingOverride.State.CLOSED,
    )

    state = meal_booking_state(camp, meal_date, meal=MealSignup.Meal.BREAKFAST, now=fixed_now)

    assert state["state"] == "open"
    assert state["locked"] is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("current_time", "expected_state"),
    [
        (time(11, 59), "open"),
        (time(12, 0), "open"),
        (time(12, 1), "open"),
    ],
)
def test_effective_booking_state_uses_cutoff_boundaries(monkeypatch, current_time, expected_state):
    today = date(2026, 7, 1)
    fixed_now = timezone.make_aware(datetime.combine(today, current_time))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: today)
    camp = CampFactory(meal_booking_cutoff_time=time(12, 0))

    state = meal_booking_state(camp, today.replace(day=2), now=fixed_now)

    assert state["state"] == expected_state
    assert state["locked"] is (expected_state != "open")


@pytest.mark.django_db
def test_override_post_requires_csrf_and_rejects_get_and_invalid_date():
    camp = CampFactory()
    manager = UserFactory()
    manager.groups.add(GroupFactory(name=HUEBERS_GROUP))
    client = Client(enforce_csrf_checks=True)
    client.force_login(manager)
    url = reverse("meal-booking-override", args=[camp.pk])

    assert client.get(url).status_code == 405
    assert client.post(url, {"meal_date": "not-a-date", "meal": "dinner", "state": "open"}).status_code == 403
    assert not MealBookingOverride.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("meal_date", "meal", "expected_count"),
    [
        ("2026-07-01", "dinner", 1),
        ("2026-06-30", "dinner", 0),
        ("2026-07-01", "breakfast", 0),
    ],
)
def test_override_post_accepts_today_dinner_only_and_rejects_past_or_breakfast(
    client, monkeypatch, meal_date, meal, expected_count
):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 7, 1))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 2))
    manager = UserFactory()
    manager.groups.add(GroupFactory(name=HUEBERS_GROUP))
    client.force_login(manager)

    response = client.post(
        reverse("meal-booking-override", args=[camp.pk]),
        {"meal_date": meal_date, "meal": meal, "state": "closed"},
    )

    assert response.status_code == 302
    assert MealBookingOverride.objects.filter(camp=camp, meal=meal).count() == expected_count


@pytest.mark.django_db
def test_repeated_override_post_is_idempotent(client, monkeypatch):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 7, 1))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 2))
    manager = UserFactory()
    manager.groups.add(GroupFactory(name=HUEBERS_GROUP))
    client.force_login(manager)
    payload = {"meal_date": "2026-07-02", "meal": "dinner", "state": "open"}
    url = reverse("meal-booking-override", args=[camp.pk])

    assert client.post(url, payload).status_code == 302
    assert client.post(url, payload).status_code == 302

    assert MealBookingOverride.objects.filter(camp=camp, meal="dinner").count() == 1
