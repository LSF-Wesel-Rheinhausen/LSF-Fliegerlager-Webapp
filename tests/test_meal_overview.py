from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from billing.models import Charge, MealOrder, MealSignup, ParticipantFamilyMember
from billing.services import calculate_meal_overview
from tests.factories import CampFactory, ParticipantFactory, SuperUserFactory


@pytest.mark.django_db
def test_calculate_meal_overview_counts_active_variants_and_retractions():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 1))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    child = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Kind",
        last_name="A",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    linked_participant = ParticipantFactory(camp=camp, first_name="Grace", last_name="B")
    deleted_charge = Charge.objects.create(
        participant=linked_participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=1,
        unit_price=Decimal("7.00"),
        occurred_on=date(2026, 7, 1),
    )
    MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.BREAKFAST,
        variant=MealSignup.Variant.NORMAL,
    )
    MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )
    MealSignup.objects.create(
        participant=participant,
        family_member=child,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.VEGAN_CHILD,
    )
    MealSignup.objects.create(
        participant=linked_participant,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.VEGAN,
        status=MealSignup.Status.RETRACTED,
        charge=deleted_charge,
    )

    overview = calculate_meal_overview(camp)

    assert len(overview[0].meals) == 1
    dinner = overview[0].meals[0]
    assert dinner.meal == MealSignup.Meal.DINNER
    assert dinner.variant_counts["Normal"] == 1
    assert dinner.variant_counts["Vegan Kind"] == 1
    assert dinner.active_total == 2
    assert dinner.retracted_total == 1


@pytest.mark.django_db
def test_camp_meal_overview_renders_counts_for_admin(client):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 1))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )
    client.force_login(SuperUserFactory())

    response = client.get(reverse("camp-meal-overview", args=[camp.pk]))

    assert response.status_code == 200
    assert b"Essens\xc3\xbcbersicht" in response.content
    assert b"N\xc3\xa4chster Tag" in response.content
    assert b"Abendessen" in response.content
    assert b"Fr\xc3\xbchst\xc3\xbcck" not in response.content
    assert b"<strong>1</strong>" in response.content


@pytest.mark.django_db
def test_meal_overview_marks_next_day_order_as_sent(client):
    camp = CampFactory()
    user = SuperUserFactory()
    client.force_login(user)

    response = client.post(reverse("meal-order-mark-sent", args=[camp.pk]))

    assert response.status_code == 302
    order = MealOrder.objects.get(camp=camp)
    assert order.ordered_by == user
