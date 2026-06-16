from datetime import date
from decimal import Decimal

import pytest

from billing.models import Charge, PriceRule
from billing.services import calculate_participant_settlement
from tests.factories import (
    CampFactory,
    ChargeFactory,
    DrinkEntryFactory,
    ExpenseFactory,
    ParticipantFactory,
    PaymentFactory,
    PriceRuleFactory,
)


@pytest.mark.django_db
def test_settlement_calculates_due_paid_advanced_and_balance():
    camp = CampFactory()
    participant = ParticipantFactory(
        camp=camp,
        first_name="Ada",
        last_name="Lovelace",
        booked_nights=2,
        actual_nights=3,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Lagerpauschale",
        unit_price=Decimal("50.00"),
        is_default=True,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.NIGHT,
        name="Übernachtung",
        unit_price=Decimal("10.00"),
        is_default=True,
    )
    ChargeFactory(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Verpflegung",
        quantity=Decimal("2"),
        unit_price=Decimal("7.50"),
    )
    DrinkEntryFactory(
        participant=participant,
        quantity=3,
        unit_price=Decimal("1.50"),
    )
    PaymentFactory(participant=participant, amount=Decimal("40.00"), paid_on=date(2025, 7, 1))
    ExpenseFactory(
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
    participant = ParticipantFactory(first_name="Grace", last_name="Hopper")
    ChargeFactory(
        participant=participant,
        kind=Charge.Kind.OTHER,
        description="Sonstiges",
        quantity=Decimal("1"),
        unit_price=Decimal("5.00"),
    )
    PaymentFactory(participant=participant, amount=Decimal("10.00"), paid_on=date(2025, 7, 1))

    result = calculate_participant_settlement(participant)

    assert result.balance == Decimal("-5.00")
    assert result.is_overpaid is True


@pytest.mark.django_db
def test_settlement_applies_price_element_subsidy_rates_for_youth_group_members():
    camp = CampFactory()
    participant = ParticipantFactory(
        camp=camp,
        first_name="Mia",
        last_name="Muster",
        is_youth_group=True,
        hilfssatz=Decimal("0.5000"),
        berufssatz=Decimal("0.3300"),
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Lagerpauschale",
        unit_price=Decimal("100.00"),
        is_default=True,
        foerdersatz=Decimal("0.4000"),
    )
    ChargeFactory(
        participant=participant,
        kind=Charge.Kind.DRINK,
        description="Getränk",
        unit_price=Decimal("10.00"),
        foerdersatz=Decimal("1.0000"),
    )

    result = calculate_participant_settlement(participant)

    assert result.total_gross == Decimal("110.00")
    assert result.total_subsidy == Decimal("8.25")
    assert result.total_due == Decimal("101.75")


@pytest.mark.django_db
def test_settlement_selects_matching_camp_flat_rate_for_companion_and_duration():
    camp = CampFactory()
    participant = ParticipantFactory(
        camp=camp,
        first_name="Bea",
        last_name="Begleitung",
        is_companion=True,
        actual_nights=10,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Teilnehmer 2 Wochen",
        unit_price=Decimal("300.00"),
        camp_flat_role=PriceRule.CampFlatRole.PARTICIPANT,
        camp_flat_duration=PriceRule.CampFlatDuration.TWO_WEEKS,
        is_default=True,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Begleitperson 2 Wochen",
        unit_price=Decimal("180.00"),
        camp_flat_role=PriceRule.CampFlatRole.COMPANION,
        camp_flat_duration=PriceRule.CampFlatDuration.TWO_WEEKS,
        is_default=True,
    )

    result = calculate_participant_settlement(participant)

    assert [line.label for line in result.lines] == ["Begleitperson 2 Wochen"]
    assert result.total_due == Decimal("180.00")


@pytest.mark.django_db
def test_participant_camp_flat_duration():
    from billing.models import PriceRule
    from billing.services import participant_camp_flat_duration

    # Test with 5 nights (should be ONE_WEEK)
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, actual_nights=5)
    result = participant_camp_flat_duration(participant)
    assert result == PriceRule.CampFlatDuration.ONE_WEEK

    # Test with 10 nights (should be TWO_WEEKS)
    participant = ParticipantFactory(camp=camp, actual_nights=10)
    result = participant_camp_flat_duration(participant)
    assert result == PriceRule.CampFlatDuration.TWO_WEEKS

    # Test with booked_nights
    participant = ParticipantFactory(camp=camp, booked_nights=3)
    result = participant_camp_flat_duration(participant)
    assert result == PriceRule.CampFlatDuration.ONE_WEEK


@pytest.mark.django_db
def test_approve_shared_expense_pro_rata():
    from billing.services import approve_shared_expense
    from billing.models import Expense, ExpenseAllocation

    camp = CampFactory()
    p1 = ParticipantFactory(camp=camp)
    p2 = ParticipantFactory(camp=camp)
    p3 = ParticipantFactory(camp=camp)

    expense = ExpenseFactory(
        camp=camp,
        amount=Decimal("10.00"),
        allocation_method=Expense.AllocationMethod.PRO_RATA,
        status=Expense.Status.PENDING,
    )

    approve_shared_expense(expense, approved_by=None, participant_ids=[p1.pk, p2.pk, p3.pk])

    assert expense.status == Expense.Status.APPROVED
    allocations = list(ExpenseAllocation.objects.filter(expense=expense).order_by("amount"))
    assert len(allocations) == 3
    
    # 10.00 / 3 = 3.333... so two get 3.33 and one gets 3.34
    amounts = sorted([a.amount for a in allocations])
    assert amounts == [Decimal("3.33"), Decimal("3.33"), Decimal("3.34")]


@pytest.mark.django_db
def test_settlement_includes_shared_expense_allocation():
    from billing.models import Expense, ExpenseAllocation
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    
    expense = ExpenseFactory(
        camp=camp,
        participant=participant,
        description="Grillkohle",
        amount=Decimal("15.00"),
        status=Expense.Status.APPROVED,
        reimbursable=True,
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        participant=participant,
        amount=Decimal("5.00")
    )

    result = calculate_participant_settlement(participant)

    # Participant gets advanced 15.00, and is allocated 5.00 due
    assert result.total_advanced == Decimal("15.00")
    assert result.total_due == Decimal("5.00")
    assert any("Umlage Grillkohle" in line.label for line in result.lines)
