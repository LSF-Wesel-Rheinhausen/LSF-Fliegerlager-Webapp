from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from tests.factories import (
    CampFactory,
    ChargeFactory,
    ExpenseFactory,
    OvernightCategoryFactory,
    ParticipantFactory,
    PaymentFactory,
    PriceRuleFactory,
    SuperUserFactory,
)

from billing.models import Charge, PriceRule, Settlement, SettlementRun
from billing.services import calculate_participant_settlement, create_settlement_run, participant_camp_flat_duration


@pytest.mark.django_db
def test_settlement_calculates_due_paid_advanced_and_balance():
    camp = CampFactory()
    category = OvernightCategoryFactory(camp=camp, name="Teilnehmer 1 Woche")
    participant = ParticipantFactory(
        camp=camp,
        overnight_category=category,
        first_name="Ada",
        last_name="Lovelace",
        arrival_date=date(2025, 7, 1),
        departure_date=date(2025, 7, 4),
    )
    PriceRuleFactory(
        camp=camp,
        overnight_category=category,
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
    ChargeFactory(
        participant=participant,
        kind=Charge.Kind.DRINK,
        description="Getränk",
        quantity=Decimal("3"),
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
def test_settlement_applies_subsidy_factor_for_youth_group_members():
    camp = CampFactory(foerdersatz=Decimal("0.5000"))
    category = OvernightCategoryFactory(camp=camp, name="Jugend")
    participant = ParticipantFactory(
        camp=camp,
        overnight_category=category,
        first_name="Mia",
        last_name="Muster",
        is_youth_group=True,
        hilfssatz=Decimal("0.5000"),
        berufssatz=Decimal("0.3300"),
    )
    PriceRuleFactory(
        camp=camp,
        overnight_category=category,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Lagerpauschale",
        unit_price=Decimal("100.00"),
        is_default=True,
        foerderfaehig=True,
    )

    result = calculate_participant_settlement(participant)

    assert result.total_gross == Decimal("100.00")
    assert result.total_subsidy == Decimal("8.25")
    assert result.total_due == Decimal("91.75")


@pytest.mark.django_db
def test_settlement_prefers_selected_overnight_category_for_camp_flat_rule():
    camp = CampFactory()
    participant_category = OvernightCategoryFactory(camp=camp, name="Begleitperson 2 Wochen")
    other_category = OvernightCategoryFactory(camp=camp, name="Teilnehmer 2 Wochen")
    participant = ParticipantFactory(
        camp=camp,
        overnight_category=participant_category,
        first_name="Bea",
        last_name="Begleitung",
        is_companion=True,
        actual_nights=10,
    )
    PriceRuleFactory(
        camp=camp,
        overnight_category=other_category,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Teilnehmer 2 Wochen",
        unit_price=Decimal("300.00"),
        is_default=True,
    )
    PriceRuleFactory(
        camp=camp,
        overnight_category=participant_category,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Begleitperson 2 Wochen",
        unit_price=Decimal("180.00"),
        is_default=True,
    )

    result = calculate_participant_settlement(participant)

    assert [line.label for line in result.lines] == ["Begleitperson 2 Wochen"]
    assert result.total_due == Decimal("180.00")


@pytest.mark.django_db
def test_participant_camp_flat_duration_uses_date_based_nights_first():
    camp = CampFactory()
    participant = ParticipantFactory(
        camp=camp,
        arrival_date=date(2025, 7, 1),
        departure_date=date(2025, 7, 6),
        actual_nights=10,
    )
    assert participant_camp_flat_duration(participant) == PriceRule.CampFlatDuration.ONE_WEEK

    participant = ParticipantFactory(
        camp=camp,
        arrival_date=date(2025, 7, 1),
        departure_date=date(2025, 7, 11),
    )
    assert participant_camp_flat_duration(participant) == PriceRule.CampFlatDuration.TWO_WEEKS

    participant = ParticipantFactory(camp=camp, booked_nights=3)
    assert participant_camp_flat_duration(participant) == PriceRule.CampFlatDuration.ONE_WEEK


@pytest.mark.django_db
def test_create_settlement_run_persists_snapshot_and_settlements():
    camp = CampFactory()
    user = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.OTHER,
        name="Werkstatt",
        unit_price=Decimal("15.00"),
        foerderfaehig=True,
        is_default=True,
    )
    ChargeFactory(
        participant=participant,
        kind=Charge.Kind.OTHER,
        description="Werkstatt",
        quantity=Decimal("1"),
        unit_price=Decimal("15.00"),
    )
    PaymentFactory(participant=participant, amount=Decimal("5.00"), paid_on=date(2025, 7, 1))

    run = create_settlement_run(camp, user)

    settlement = Settlement.objects.get(run=run, participant=participant)

    assert SettlementRun.objects.count() == 1
    assert run.camp == camp
    assert run.created_by == user
    assert run.participant_count == 1
    assert run.total_due == Decimal("15.00")
    assert run.total_paid == Decimal("5.00")
    assert run.balance == Decimal("10.00")
    assert run.data == {"source": "live_calculation"}
    assert settlement.total_due == Decimal("15.00")
    assert settlement.total_paid == Decimal("5.00")
    assert settlement.balance == Decimal("10.00")
    assert settlement.data["participant"]["first_name"] == "Ada"
    assert settlement.data["totals"]["due"] == "15.00"
    assert settlement.data["lines"][0]["label"] == "Werkstatt"


@pytest.mark.django_db
def test_saved_settlement_run_can_be_exported_as_csv(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    ChargeFactory(
        participant=participant,
        kind=Charge.Kind.OTHER,
        description="Werkstatt",
        quantity=Decimal("1"),
        unit_price=Decimal("15.00"),
    )
    client.force_login(user)

    create_response = client.post(reverse("settlement-run-create", args=[camp.pk]))
    run = SettlementRun.objects.get()

    export_response = client.get(reverse("export-settlement-run-csv", args=[run.pk]))
    content = export_response.content.decode()

    assert create_response.status_code == 302
    assert create_response.url == reverse("settlement-run-detail", args=[run.pk])
    assert export_response.status_code == 200
    assert export_response["Content-Disposition"] == f'attachment; filename="abrechnungslauf-{camp.year}-{run.pk}.csv"'
    assert "Nachname,Vorname,Brutto,Förderung,Soll,Gezahlt,Vorgestreckt,Offen" in content
    assert "Lovelace,Ada,15.00,0.00,15.00,0.00,0.00,15.00" in content
