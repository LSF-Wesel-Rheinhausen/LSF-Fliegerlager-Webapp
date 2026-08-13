from decimal import Decimal

import pytest

from billing.forms import MealStandardPricesForm
from billing.models import Charge, MealSignup, PriceRule
from billing.services import calculate_participant_settlement
from tests.factories import CampFactory, ParticipantFactory


@pytest.mark.django_db
def test_updating_meal_price_rules_syncs_existing_meal_signup_and_charge_foerdersatz():
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(
        camp=camp, is_youth_group=True, hilfssatz=Decimal("1.0000"), berufssatz=Decimal("1.0000")
    )

    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type="dinner",
        is_default=True,
        applies_to_adults=True,
        unit_price=Decimal("10.00"),
        foerdersatz=Decimal("0.0000"),
    )

    signup = MealSignup.objects.create(
        participant=participant,
        meal_date="2026-08-14",
        meal="dinner",
        variant="normal",
        status=MealSignup.Status.ACTIVE,
        foerdersatz=Decimal("0.0000"),
    )
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        occurred_on="2026-08-14",
        description="Standard Abendessen",
        quantity=Decimal("1"),
        unit_price=Decimal("10.00"),
        foerdersatz=Decimal("0.0000"),
    )
    signup.charge = charge
    signup.save()

    initial_settlement = calculate_participant_settlement(participant)
    assert initial_settlement.total_subsidy == Decimal("0.00")

    form_data = {
        "breakfast_adult_price": "5.00",
        "breakfast_adult_foerdersatz": "0.00",
        "breakfast_child_price": "3.00",
        "breakfast_child_foerdersatz": "0.00",
        "dinner_adult_price": "10.00",
        "dinner_adult_foerdersatz": "50.00",
        "dinner_child_price": "6.00",
        "dinner_child_foerdersatz": "50.00",
        "snack_adult_price": "2.00",
        "snack_adult_foerdersatz": "0.00",
        "snack_child_price": "1.00",
        "snack_child_foerdersatz": "0.00",
    }
    form = MealStandardPricesForm(form_data, camp=camp)
    assert form.is_valid()
    form.save()

    signup.refresh_from_db()
    charge.refresh_from_db()

    assert signup.foerdersatz == Decimal("0.5000")
    assert charge.foerdersatz == Decimal("0.5000")

    settlement_after = calculate_participant_settlement(participant)
    assert settlement_after.total_subsidy == Decimal("5.00")
    assert settlement_after.total_due == Decimal("5.00")
