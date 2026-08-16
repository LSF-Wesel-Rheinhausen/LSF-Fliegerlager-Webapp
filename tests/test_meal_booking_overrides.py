from datetime import date, datetime, time

import pytest
from django.urls import reverse
from django.utils import timezone

from billing.models import MealBookingOverride, MealSignup
from billing.permissions import HUEBERS_GROUP
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
    ParticipantFactory(camp=camp)
    manager = UserFactory()
    manager.groups.add(GroupFactory(name=HUEBERS_GROUP))
    override = MealBookingOverride.objects.create(
        camp=camp,
        meal_date=date(2026, 7, 2),
        meal=MealSignup.Meal.DINNER,
        state=MealBookingOverride.State.OPEN,
        changed_by=manager,
    )

    assert override.changed_by == manager
    assert kiosk_client.get(reverse("kiosk-home")).status_code == 200
