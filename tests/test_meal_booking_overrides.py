from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.db.models import QuerySet
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from billing.kiosk_access import KIOSK_PARTICIPANT_SESSION_KEY
from billing.models import Camp, Charge, MealBookingOverride, MealOrder, MealSignup, PriceRule
from billing.permissions import HUEBERS_GROUP
from billing.services import meal_booking_state
from tests.factories import CampFactory, GroupFactory, ParticipantFactory, PriceRuleFactory, UserFactory


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
@pytest.mark.parametrize("override_state", [MealBookingOverride.State.OPEN, MealBookingOverride.State.CLOSED])
def test_sent_catering_order_takes_precedence_over_manual_override(override_state):
    today = timezone.localdate()
    meal_date = today + timedelta(days=1)
    camp = CampFactory(starts_on=today, ends_on=meal_date)
    MealBookingOverride.objects.create(
        camp=camp,
        meal_date=meal_date,
        meal=MealSignup.Meal.DINNER,
        state=override_state,
    )
    MealOrder.objects.create(camp=camp, meal_date=meal_date, is_sent=True)

    state = meal_booking_state(camp, meal_date, meal=MealSignup.Meal.DINNER)

    assert state == {
        "state": "order_sent",
        "locked": True,
        "message": f"Die Bestellung für {meal_date:%d.%m.%Y} wurde bereits abgeschickt.",
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("override_state", "expected_state", "expected_locked"),
    [
        (MealBookingOverride.State.OPEN, "manual_open", False),
        (MealBookingOverride.State.CLOSED, "manual_closed", True),
    ],
)
def test_not_sent_order_restores_stored_manual_state(override_state, expected_state, expected_locked):
    today = timezone.localdate()
    meal_date = today + timedelta(days=1)
    camp = CampFactory(starts_on=today, ends_on=meal_date)
    MealBookingOverride.objects.create(
        camp=camp,
        meal_date=meal_date,
        meal=MealSignup.Meal.DINNER,
        state=override_state,
    )
    MealOrder.objects.create(camp=camp, meal_date=meal_date, is_sent=False)

    state = meal_booking_state(camp, meal_date, meal=MealSignup.Meal.DINNER)

    assert state["state"] == expected_state
    assert state["locked"] is expected_locked


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
    MealOrder.objects.create(camp=camp, meal_date=meal_date, is_sent=True)

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


@pytest.mark.django_db
def test_open_override_for_sent_order_explains_that_order_still_locks(client, monkeypatch):
    today = date(2026, 7, 1)
    meal_date = date(2026, 7, 2)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: today)
    monkeypatch.setattr("billing.views.timezone.localdate", lambda: today)
    camp = CampFactory(starts_on=today, ends_on=meal_date)
    MealOrder.objects.create(camp=camp, meal_date=meal_date, is_sent=True)
    manager = UserFactory()
    manager.groups.add(GroupFactory(name=HUEBERS_GROUP))
    client.force_login(manager)

    response = client.post(
        reverse("meal-booking-override", args=[camp.pk]),
        {"meal_date": meal_date.isoformat(), "meal": "dinner", "state": "open"},
    )

    response_messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert response.status_code == 302
    assert any(
        "wegen der versandten Bestellung" in message and "bis zur Markierung als nicht bestellt gesperrt" in message
        for message in response_messages
    )


@pytest.mark.django_db
def test_booking_rechecks_manual_close_after_acquiring_camp_lock(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 6, 30, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    first_meal_date = date(2026, 7, 1)
    meal_date = date(2026, 7, 2)
    camp = CampFactory(starts_on=fixed_now.date(), ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    original_fetch_all = QuerySet._fetch_all
    override_injected = False

    def close_booking_before_camp_lock(queryset):
        nonlocal override_injected
        was_unfetched = queryset._result_cache is None
        if was_unfetched and not override_injected and queryset.query.select_for_update and queryset.model is Camp:
            override_injected = True
            MealBookingOverride.objects.create(
                camp=camp,
                meal_date=meal_date,
                meal=MealSignup.Meal.DINNER,
                state=MealBookingOverride.State.CLOSED,
            )
        original_fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", close_booking_before_camp_lock)

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": [first_meal_date.isoformat(), meal_date.isoformat()],
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
            "meal-target": [f"participant-{participant.pk}"],
            f"meal-variant-participant-{participant.pk}": MealSignup.Variant.NORMAL,
        },
    )

    assert override_injected is True
    assert response.status_code == 302
    assert not MealSignup.objects.filter(
        participant=participant,
        meal_date__in=[first_meal_date, meal_date],
    ).exists()
    assert not Charge.objects.filter(
        participant=participant,
        occurred_on__in=[first_meal_date, meal_date],
    ).exists()


@pytest.mark.django_db
def test_retraction_rechecks_manual_close_after_acquiring_camp_lock(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 6, 30, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    meal_date = date(2026, 7, 2)
    camp = CampFactory(starts_on=fixed_now.date(), ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=1,
        unit_price=Decimal("7.00"),
        occurred_on=meal_date,
    )
    signup = MealSignup.objects.create(
        participant=participant,
        meal_date=meal_date,
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        charge=charge,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    original_fetch_all = QuerySet._fetch_all
    override_injected = False

    def close_booking_before_camp_lock(queryset):
        nonlocal override_injected
        was_unfetched = queryset._result_cache is None
        if was_unfetched and not override_injected and queryset.query.select_for_update and queryset.model is Camp:
            override_injected = True
            MealBookingOverride.objects.create(
                camp=camp,
                meal_date=meal_date,
                meal=MealSignup.Meal.DINNER,
                state=MealBookingOverride.State.CLOSED,
            )
        original_fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", close_booking_before_camp_lock)

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {"action": "meal_retract", "meal_signup_id": signup.pk},
    )

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert override_injected is True
    assert response.status_code == 200
    assert signup.status == MealSignup.Status.ACTIVE
    assert charge.deleted_at is None
