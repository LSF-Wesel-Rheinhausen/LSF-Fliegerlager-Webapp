from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from billing.models import Camp, Charge, DrinkEntry, Expense, Participant, Payment, PriceRule
from billing.services import calculate_participant_settlement


@pytest.mark.django_db
def test_settlement_calculates_due_paid_advanced_and_balance():
    camp = Camp.objects.create(name="Fliegerlager", year=2025)
    participant = Participant.objects.create(
        camp=camp,
        first_name="Ada",
        last_name="Lovelace",
        booked_nights=2,
        actual_nights=3,
    )
    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Lagerpauschale",
        unit_price=Decimal("50.00"),
        is_default=True,
    )
    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.NIGHT,
        name="Übernachtung",
        unit_price=Decimal("10.00"),
        is_default=True,
    )
    Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Verpflegung",
        quantity=Decimal("2"),
        unit_price=Decimal("7.50"),
    )
    DrinkEntry.objects.create(
        participant=participant,
        drink=DrinkEntry.Drink.WATER,
        quantity=3,
        unit_price=Decimal("1.50"),
        booked_at=timezone.datetime(2025, 7, 1, 12, 0, tzinfo=timezone.get_current_timezone()),
    )
    Payment.objects.create(participant=participant, amount=Decimal("40.00"), paid_on=date(2025, 7, 1))
    Expense.objects.create(
        camp=camp,
        participant=participant,
        category="Einkauf",
        description="Brötchen",
        amount=Decimal("12.00"),
        reimbursable=True,
    )

    result = calculate_participant_settlement(participant)

    assert result.total_due == Decimal("99.50")
    assert result.total_paid == Decimal("40.00")
    assert result.total_advanced == Decimal("12.00")
    assert result.balance == Decimal("47.50")


@pytest.mark.django_db
def test_settlement_allows_overpayment():
    camp = Camp.objects.create(name="Fliegerlager", year=2025)
    participant = Participant.objects.create(camp=camp, first_name="Grace", last_name="Hopper")
    Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.OTHER,
        description="Sonstiges",
        quantity=Decimal("1"),
        unit_price=Decimal("5.00"),
    )
    Payment.objects.create(participant=participant, amount=Decimal("10.00"), paid_on=date(2025, 7, 1))

    result = calculate_participant_settlement(participant)

    assert result.balance == Decimal("-5.00")
    assert result.is_overpaid is True
