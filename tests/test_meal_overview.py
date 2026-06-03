from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from billing.models import BookingAuditLog, Charge, MealSignup
from billing.permissions import EDITOR_GROUP
from billing.services import camp_meal_overview, cancel_meal_signup, restore_meal_signup
from tests.factories import (
    ChargeFactory,
    GroupFactory,
    MealSignupFactory,
    ParticipantFactory,
    SuperUserFactory,
    UserFactory,
)


@pytest.mark.django_db
def test_camp_meal_overview_groups_active_signups_by_day_meal_and_variant():
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    MealSignupFactory(
        participant=participant,
        meal_date=date(2025, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.VEGAN,
    )
    cancelled_participant = ParticipantFactory(camp=participant.camp, first_name="Grace", last_name="Hopper")
    MealSignupFactory(
        participant=cancelled_participant,
        meal_date=date(2025, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        is_cancelled=True,
        cancellation_note="Faehrt frueher heim",
    )

    groups = camp_meal_overview(participant.camp)

    assert len(groups) == 1
    assert groups[0]["meal_date"] == date(2025, 7, 1)
    assert groups[0]["meal_label"] == "Abendessen"
    assert groups[0]["active_count"] == 1
    assert groups[0]["cancelled_count"] == 1
    assert groups[0]["variant_counts"] == {"Vegan": 1}


@pytest.mark.django_db
def test_cancel_and_restore_meal_signup_updates_signup_charge_and_audit_log():
    admin = SuperUserFactory(username="admin")
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    signup = MealSignupFactory(
        participant=participant,
        meal_date=date(2025, 7, 1),
        meal=MealSignup.Meal.DINNER,
    )
    charge = ChargeFactory(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen Abendessen",
        quantity=Decimal("1.00"),
        unit_price=Decimal("7.00"),
        occurred_on=date(2025, 7, 1),
    )

    cancel_log = cancel_meal_signup(signup, changed_by=admin, note="Teilnehmer abgereist")

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.is_cancelled is True
    assert signup.cancellation_note == "Teilnehmer abgereist"
    assert charge.is_cancelled is True
    assert charge.cancellation_note == "Teilnehmer abgereist"
    assert cancel_log.action == BookingAuditLog.Action.CANCELLED
    assert cancel_log.before["is_cancelled"] is False
    assert cancel_log.after["is_cancelled"] is True

    restore_log = restore_meal_signup(signup, changed_by=admin)

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.is_cancelled is False
    assert signup.cancellation_note == ""
    assert charge.is_cancelled is False
    assert charge.cancellation_note == ""
    assert restore_log.action == BookingAuditLog.Action.RESTORED
    assert restore_log.before["is_cancelled"] is True
    assert restore_log.after["is_cancelled"] is False


@pytest.mark.django_db
def test_admin_can_view_cancel_and_restore_meal_signup(client):
    admin = SuperUserFactory(username="admin")
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    signup = MealSignupFactory(participant=participant)
    charge = ChargeFactory(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen Abendessen",
        occurred_on=signup.meal_date,
    )
    client.force_login(admin)

    overview_response = client.get(reverse("meal-overview", args=[participant.camp.pk]))
    cancel_response = client.post(
        reverse("meal-signup-cancel", args=[signup.pk]),
        {"cancellation_note": "Krank gemeldet"},
    )

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert overview_response.status_code == 200
    assert b"Mahlzeiten\xc3\xbcbersicht" in overview_response.content
    assert b"Ada Lovelace" in overview_response.content
    assert cancel_response.status_code == 302
    assert signup.is_cancelled is True
    assert charge.is_cancelled is True

    restore_response = client.post(reverse("meal-signup-restore", args=[signup.pk]))

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert restore_response.status_code == 302
    assert signup.is_cancelled is False
    assert charge.is_cancelled is False


@pytest.mark.django_db
def test_meal_signup_cancel_requires_note(client):
    admin = SuperUserFactory(username="admin")
    signup = MealSignupFactory()
    client.force_login(admin)

    response = client.post(reverse("meal-signup-cancel", args=[signup.pk]), {"cancellation_note": ""})

    signup.refresh_from_db()
    assert response.status_code == 302
    assert signup.is_cancelled is False
    assert BookingAuditLog.objects.count() == 0


@pytest.mark.django_db
def test_editor_cannot_use_meal_admin_views(client):
    editor = UserFactory(username="editor")
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    signup = MealSignupFactory()
    client.force_login(editor)

    overview_response = client.get(reverse("meal-overview", args=[signup.participant.camp.pk]))
    cancel_response = client.post(
        reverse("meal-signup-cancel", args=[signup.pk]),
        {"cancellation_note": "Nicht erlaubt"},
    )
    restore_response = client.post(reverse("meal-signup-restore", args=[signup.pk]))

    signup.refresh_from_db()
    assert reverse("login") in overview_response["Location"]
    assert reverse("login") in cancel_response["Location"]
    assert reverse("login") in restore_response["Location"]
    assert signup.is_cancelled is False
