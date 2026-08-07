from decimal import Decimal

import pytest

from billing.models import Charge, Expense, Participant, PriceRule
from billing.services import get_cost_center_evaluation
from tests.factories import CampFactory, ParticipantFactory


@pytest.mark.django_db
def test_cost_center_evaluation_aggregates_camp_flat():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)

    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Lagerpauschale",
        unit_price=Decimal("150.00"),
        foerdersatz=Decimal("0.50"),
        is_default=True,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        camp_flat_role=PriceRule.CampFlatRole.PARTICIPANT,
    )
    participant.booked_nights = 7
    participant.save()

    Charge.objects.create(
        participant=participant, kind=Charge.Kind.CAMP_FLAT, unit_price=Decimal("50.00"), description="Manual Flat"
    )

    Expense.objects.create(
        camp=camp,
        amount=Decimal("100.00"),
        cost_center=Expense.CostCenter.FOOD_OTHER,
        allocation_method=Expense.AllocationMethod.COST_CENTER,
        status=Expense.Status.APPROVED,
    )

    eval_data = get_cost_center_evaluation(camp)
    camp_flat = eval_data.get("camp_flat")

    assert camp_flat is not None
    assert camp_flat["income"] == Decimal("200.00")  # 150 automated gross + 50 manual
    assert camp_flat["expense_total"] == Decimal("100.00")
    assert camp_flat["balance"] == Decimal("100.00")


@pytest.mark.django_db
def test_cost_center_evaluation_aggregates_subsidies_and_donations():
    camp = CampFactory()
    participant = ParticipantFactory(
        camp=camp,
        status=Participant.Status.ACTIVE,
        is_youth_group=True,
        hilfssatz=Decimal("1.00"),
        berufssatz=Decimal("1.00"),
    )

    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Lagerpauschale",
        unit_price=Decimal("150.00"),
        foerdersatz=Decimal("0.50"),
        is_default=True,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        camp_flat_role=PriceRule.CampFlatRole.PARTICIPANT,
    )
    participant.booked_nights = 7
    participant.save()

    Charge.objects.create(
        participant=participant, kind=Charge.Kind.DONATION, unit_price=Decimal("200.00"), description="Spende"
    )

    eval_data = get_cost_center_evaluation(camp)
    subsidies = eval_data.get("subsidies")

    assert subsidies is not None
    assert subsidies["income"] == Decimal("200.00")
    assert subsidies["expense_total"] == Decimal("75.00")  # 50% of 150.00
    assert subsidies["balance"] == Decimal("125.00")
