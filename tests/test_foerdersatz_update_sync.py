from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from billing.forms import MealStandardPricesForm, PriceRuleForm
from billing.models import Charge, MealSignup, ParticipantFamilyMember, PriceRule
from billing.services import (
    calculate_participant_settlement,
    create_settlement_run,
    is_charge_covered_by_settlement_run,
    sync_meal_signup_charges_for_camp,
)
from tests.factories import (
    CampFactory,
    ParticipantFactory,
    ParticipantFamilyMemberFactory,
    SuperUserFactory,
    UserFactory,
)


def _create_meal_signup_with_charge(camp, *, meal_date, foerdersatz=Decimal("0.1000")):
    participant = ParticipantFactory(camp=camp)
    signup = MealSignup.objects.create(
        participant=participant,
        meal_date=meal_date,
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        status=MealSignup.Status.ACTIVE,
        foerdersatz=foerdersatz,
    )
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        occurred_on=meal_date,
        description="Abendessen",
        quantity=Decimal("1"),
        unit_price=Decimal("10.00"),
        foerdersatz=foerdersatz,
    )
    signup.charge = charge
    signup.save(update_fields=["charge"])
    return signup, charge


def _create_dinner_rule(camp, *, foerdersatz, unit_price=Decimal("10.00"), **kwargs):
    applies_to_adults = kwargs.pop("applies_to_adults", True)
    return PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        applies_to_adults=applies_to_adults,
        foerdersatz=foerdersatz,
        unit_price=unit_price,
        **kwargs,
    )


@pytest.mark.django_db
def test_updating_meal_price_rules_syncs_existing_meal_signup_and_charge_foerdersatz():
    camp = CampFactory(is_active=True, name="Camp Alpha 2026")
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
        meal_date=date(2026, 8, 14),
        meal="dinner",
        variant="normal",
        status=MealSignup.Status.ACTIVE,
        foerdersatz=Decimal("0.0000"),
    )
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        occurred_on=date(2026, 8, 14),
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


@pytest.mark.django_db
def test_child_family_member_meal_signup_syncs_with_child_price_rule():
    camp = CampFactory(is_active=True, name="Camp Beta 2026")
    guardian = ParticipantFactory(
        camp=camp, is_youth_group=True, hilfssatz=Decimal("1.0000"), berufssatz=Decimal("1.0000")
    )
    child = ParticipantFamilyMemberFactory(
        guardian=guardian, role=ParticipantFamilyMember.Role.CHILD, is_youth_group=True
    )

    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type="dinner",
        is_default=True,
        applies_to_children=True,
        unit_price=Decimal("6.00"),
        foerdersatz=Decimal("0.0000"),
    )

    signup = MealSignup.objects.create(
        participant=guardian,
        family_member=child,
        meal_date=date(2026, 8, 14),
        meal="dinner",
        variant="normal_child",
        status=MealSignup.Status.ACTIVE,
        foerdersatz=Decimal("0.0000"),
    )
    charge = Charge.objects.create(
        participant=guardian,
        family_member=child,
        kind=Charge.Kind.FOOD,
        occurred_on=date(2026, 8, 14),
        description=f"Standard Abendessen für {child.full_name}",
        quantity=Decimal("1"),
        unit_price=Decimal("6.00"),
        foerdersatz=Decimal("0.0000"),
    )
    signup.charge = charge
    signup.save()

    form_data = {
        "breakfast_adult_price": "5.00",
        "breakfast_adult_foerdersatz": "0.00",
        "breakfast_child_price": "3.00",
        "breakfast_child_foerdersatz": "0.00",
        "dinner_adult_price": "10.00",
        "dinner_adult_foerdersatz": "20.00",
        "dinner_child_price": "6.00",
        "dinner_child_foerdersatz": "40.00",
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

    assert signup.foerdersatz == Decimal("0.4000")
    assert charge.foerdersatz == Decimal("0.4000")


@pytest.mark.django_db
def test_pricerule_form_save_triggers_meal_signup_sync():
    camp = CampFactory(is_active=True, name="Camp Gamma 2026")
    participant = ParticipantFactory(
        camp=camp, is_youth_group=True, hilfssatz=Decimal("1.0000"), berufssatz=Decimal("1.0000")
    )

    rule = PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type="breakfast",
        is_default=True,
        applies_to_adults=True,
        unit_price=Decimal("5.00"),
        foerdersatz=Decimal("0.1000"),
    )

    signup = MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 8, 14),
        meal="breakfast",
        variant="normal",
        status=MealSignup.Status.ACTIVE,
        foerdersatz=Decimal("0.1000"),
    )
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        occurred_on=date(2026, 8, 14),
        description="Frühstück",
        quantity=Decimal("1"),
        unit_price=Decimal("5.00"),
        foerdersatz=Decimal("0.1000"),
    )
    signup.charge = charge
    signup.save()

    form_data = {
        "kind": PriceRule.Kind.MEAL,
        "name": "Standard Frühstück",
        "unit_price": "5.00",
        "foerdersatz": "30.00",
        "meal_type": "breakfast",
        "applies_to_adults": True,
        "is_default": True,
    }
    form = PriceRuleForm(form_data, instance=rule)
    assert form.is_valid()
    form.save()

    signup.refresh_from_db()
    charge.refresh_from_db()

    assert signup.foerdersatz == Decimal("0.3000")
    assert charge.foerdersatz == Decimal("0.3000")


@pytest.mark.django_db
def test_date_specific_meal_price_rule_takes_precedence_in_sync():
    camp = CampFactory(is_active=True, name="Camp Delta 2026")
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
        foerdersatz=Decimal("0.1000"),
    )

    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type="dinner",
        meal_date=date(2026, 8, 15),
        is_default=False,
        applies_to_adults=True,
        unit_price=Decimal("15.00"),
        foerdersatz=Decimal("0.5000"),
    )

    signup = MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 8, 15),
        meal="dinner",
        variant="normal",
        status=MealSignup.Status.ACTIVE,
        foerdersatz=Decimal("0.1000"),
    )
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        occurred_on=date(2026, 8, 15),
        description="Festessen Abendessen",
        quantity=Decimal("1"),
        unit_price=Decimal("10.00"),
        foerdersatz=Decimal("0.1000"),
    )
    signup.charge = charge
    signup.save()

    sync_meal_signup_charges_for_camp(camp)

    signup.refresh_from_db()
    charge.refresh_from_db()

    assert signup.foerdersatz == Decimal("0.5000")
    assert charge.foerdersatz == Decimal("0.5000")
    assert charge.unit_price == Decimal("15.00")


@pytest.mark.django_db
def test_sync_ignores_archived_meal_price_rules():
    camp = CampFactory(is_active=True)
    signup, charge = _create_meal_signup_with_charge(camp, meal_date=date(2026, 8, 15))
    _create_dinner_rule(camp, foerdersatz=Decimal("0.2000"), is_default=True)
    _create_dinner_rule(
        camp,
        foerdersatz=Decimal("0.9000"),
        unit_price=Decimal("99.00"),
        meal_date=date(2026, 8, 15),
        is_archived=True,
    )

    assert sync_meal_signup_charges_for_camp(camp) == 1

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.foerdersatz == Decimal("0.2000")
    assert charge.foerdersatz == Decimal("0.2000")
    assert charge.unit_price == Decimal("10.00")


@pytest.mark.django_db
def test_sync_does_not_mutate_signup_linked_to_deleted_charge():
    camp = CampFactory(is_active=True)
    signup, charge = _create_meal_signup_with_charge(camp, meal_date=date(2026, 8, 15))
    charge.deleted_at = timezone.now()
    charge.save(update_fields=["deleted_at"])
    _create_dinner_rule(camp, foerdersatz=Decimal("0.8000"), is_default=True, unit_price=Decimal("20.00"))

    assert sync_meal_signup_charges_for_camp(camp) == 0

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.foerdersatz == Decimal("0.1000")
    assert charge.foerdersatz == Decimal("0.1000")
    assert charge.unit_price == Decimal("10.00")


@pytest.mark.django_db
def test_sync_does_not_mutate_past_meal_signup(monkeypatch):
    camp = CampFactory(is_active=True)
    signup, charge = _create_meal_signup_with_charge(camp, meal_date=date(2026, 8, 14))
    _create_dinner_rule(camp, foerdersatz=Decimal("0.8000"), is_default=True, unit_price=Decimal("20.00"))
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 8, 15))

    assert sync_meal_signup_charges_for_camp(camp) == 0

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.foerdersatz == Decimal("0.1000")
    assert charge.foerdersatz == Decimal("0.1000")
    assert charge.unit_price == Decimal("10.00")


@pytest.mark.django_db
def test_sync_does_not_mutate_charge_in_settlement_snapshot():
    camp = CampFactory(is_active=True)
    signup, charge = _create_meal_signup_with_charge(camp, meal_date=date(2026, 8, 14))
    _create_dinner_rule(camp, foerdersatz=Decimal("0.8000"), is_default=True, unit_price=Decimal("20.00"))
    create_settlement_run(camp, None)

    assert sync_meal_signup_charges_for_camp(camp) == 0

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.foerdersatz == Decimal("0.1000")
    assert charge.foerdersatz == Decimal("0.1000")
    assert charge.unit_price == Decimal("10.00")


@pytest.mark.django_db
def test_sync_rolls_back_signup_when_charge_update_fails(monkeypatch):
    camp = CampFactory(is_active=True)
    signup, charge = _create_meal_signup_with_charge(camp, meal_date=date(2026, 8, 15))
    _create_dinner_rule(camp, foerdersatz=Decimal("0.8000"), is_default=True, unit_price=Decimal("20.00"))
    original_save = Charge.save

    def failing_save(self, *args, **kwargs):
        if self.pk == charge.pk and kwargs.get("update_fields") == ["foerdersatz", "unit_price", "updated_at"]:
            raise DatabaseError("simulated charge write failure")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(Charge, "save", failing_save)
    with pytest.raises(DatabaseError, match="simulated charge write failure"):
        sync_meal_signup_charges_for_camp(camp)

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.foerdersatz == Decimal("0.1000")
    assert charge.foerdersatz == Decimal("0.1000")
    assert charge.unit_price == Decimal("10.00")


@pytest.mark.django_db
def test_sync_is_idempotent_for_already_synchronized_future_signup():
    camp = CampFactory(is_active=True)
    signup, charge = _create_meal_signup_with_charge(camp, meal_date=date(2026, 8, 15))
    _create_dinner_rule(camp, foerdersatz=Decimal("0.8000"), is_default=True, unit_price=Decimal("20.00"))

    assert sync_meal_signup_charges_for_camp(camp) == 1
    signup.refresh_from_db()
    charge.refresh_from_db()
    first_signup_updated_at = signup.updated_at
    first_charge_updated_at = charge.updated_at

    assert sync_meal_signup_charges_for_camp(camp) == 0

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.updated_at == first_signup_updated_at
    assert charge.updated_at == first_charge_updated_at


@pytest.mark.django_db
def test_price_rule_create_view_resyncs_future_meal_signup(client, monkeypatch):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 8, 14))
    camp = CampFactory(is_active=True)
    _create_dinner_rule(camp, foerdersatz=Decimal("0.2000"), is_default=True)
    signup, charge = _create_meal_signup_with_charge(camp, meal_date=date(2026, 8, 15))
    client.force_login(SuperUserFactory())

    response = client.post(
        reverse("price-rule-create", args=[camp.pk]),
        {
            "kind": PriceRule.Kind.MEAL,
            "name": "Festessen",
            "unit_price": "18.00",
            "foerdersatz": "60",
            "meal_type": MealSignup.Meal.DINNER,
            "meal_date": "2026-08-15",
            "applies_to_adults": "on",
        },
    )

    assert response.status_code == 302
    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.foerdersatz == Decimal("0.6000")
    assert charge.foerdersatz == Decimal("0.6000")
    assert charge.unit_price == Decimal("18.00")


@pytest.mark.django_db
def test_price_rule_archive_view_resyncs_future_meal_signup(client, monkeypatch):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 8, 14))
    camp = CampFactory(is_active=True)
    _create_dinner_rule(camp, foerdersatz=Decimal("0.2000"), is_default=True)
    date_rule = _create_dinner_rule(
        camp,
        foerdersatz=Decimal("0.6000"),
        unit_price=Decimal("18.00"),
        meal_date=date(2026, 8, 15),
    )
    signup, charge = _create_meal_signup_with_charge(
        camp,
        meal_date=date(2026, 8, 15),
        foerdersatz=Decimal("0.6000"),
    )
    charge.unit_price = Decimal("18.00")
    charge.save(update_fields=["unit_price"])
    client.force_login(SuperUserFactory())

    response = client.post(reverse("price-rule-delete", args=[date_rule.pk]))

    assert response.status_code == 302
    date_rule.refresh_from_db()
    signup.refresh_from_db()
    charge.refresh_from_db()
    assert date_rule.is_archived is True
    assert signup.foerdersatz == Decimal("0.2000")
    assert charge.foerdersatz == Decimal("0.2000")
    assert charge.unit_price == Decimal("10.00")


@pytest.mark.django_db
def test_admin_price_rule_edit_resyncs_mutable_charge_and_settlement_view(client, monkeypatch):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 8, 14))
    camp = CampFactory(is_active=True)
    rule = _create_dinner_rule(camp, foerdersatz=Decimal("0.2000"), is_default=True, name="Abendessen")
    signup, charge = _create_meal_signup_with_charge(
        camp,
        meal_date=date(2026, 8, 15),
        foerdersatz=Decimal("0.2000"),
    )
    signup.participant.is_youth_group = True
    signup.participant.hilfssatz = Decimal("1.0000")
    signup.participant.berufssatz = Decimal("1.0000")
    signup.participant.save(update_fields=["is_youth_group", "hilfssatz", "berufssatz"])
    client.force_login(SuperUserFactory())

    response = client.post(
        reverse("price-rule-edit", args=[rule.pk]),
        {
            "kind": PriceRule.Kind.MEAL,
            "name": "Abendessen",
            "unit_price": "20.00",
            "foerdersatz": "80",
            "meal_type": MealSignup.Meal.DINNER,
            "is_default": "on",
            "applies_to_adults": "on",
        },
    )

    assert response.status_code == 302
    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.foerdersatz == Decimal("0.8000")
    assert charge.unit_price == Decimal("20.00")
    assert charge.foerdersatz == Decimal("0.8000")
    settlement = calculate_participant_settlement(signup.participant)
    assert settlement.total_gross == Decimal("20.00")
    assert settlement.total_subsidy == Decimal("16.00")
    assert settlement.total_due == Decimal("4.00")


@pytest.mark.django_db
def test_non_admin_cannot_edit_or_archive_meal_price_rule(client):
    camp = CampFactory(is_active=True)
    rule = _create_dinner_rule(camp, foerdersatz=Decimal("0.2000"), is_default=False)
    client.force_login(UserFactory())
    edit_payload = {
        "kind": PriceRule.Kind.MEAL,
        "name": "Manipuliert",
        "unit_price": "99.00",
        "foerdersatz": "100",
        "meal_type": MealSignup.Meal.DINNER,
        "applies_to_adults": "on",
    }

    edit_response = client.post(reverse("price-rule-edit", args=[rule.pk]), edit_payload)
    archive_response = client.post(reverse("price-rule-delete", args=[rule.pk]))

    assert edit_response.status_code == 302
    assert archive_response.status_code == 302
    rule.refresh_from_db()
    assert rule.name != "Manipuliert"
    assert rule.foerdersatz == Decimal("0.2000")
    assert rule.is_archived is False


@pytest.mark.django_db
def test_sync_uses_companion_rule_and_youth_subsidy_with_guardian_payment_ownership(monkeypatch):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 8, 14))
    camp = CampFactory(is_active=True)
    guardian = ParticipantFactory(camp=camp, is_youth_group=False)
    family_companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role=ParticipantFamilyMember.Role.COMPANION,
        is_youth_group=True,
    )
    regular_companion = ParticipantFactory(
        camp=camp,
        is_companion=True,
        is_youth_group=True,
        hilfssatz=Decimal("1.0000"),
        berufssatz=Decimal("1.0000"),
    )
    _create_dinner_rule(
        camp,
        foerdersatz=Decimal("0.1000"),
        unit_price=Decimal("10.00"),
        is_default=True,
        applies_to_companions=False,
    )
    companion_rule = _create_dinner_rule(
        camp,
        foerdersatz=Decimal("1.0000"),
        unit_price=Decimal("12.00"),
        is_default=True,
        applies_to_adults=False,
        applies_to_companions=True,
    )
    family_signup = MealSignup.objects.create(
        participant=guardian,
        family_member=family_companion,
        meal_date=date(2026, 8, 15),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        foerdersatz=Decimal("0.1000"),
    )
    family_charge = Charge.objects.create(
        participant=guardian,
        family_member=family_companion,
        kind=Charge.Kind.FOOD,
        description="Begleiter-Abendessen",
        quantity=Decimal("1"),
        unit_price=Decimal("10.00"),
        foerdersatz=Decimal("0.1000"),
        occurred_on=date(2026, 8, 15),
    )
    family_signup.charge = family_charge
    family_signup.save(update_fields=["charge"])
    regular_signup = MealSignup.objects.create(
        participant=regular_companion,
        meal_date=date(2026, 8, 15),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        foerdersatz=Decimal("0.1000"),
    )
    regular_charge = Charge.objects.create(
        participant=regular_companion,
        kind=Charge.Kind.FOOD,
        description="Begleiter-Abendessen",
        quantity=Decimal("1"),
        unit_price=Decimal("10.00"),
        foerdersatz=Decimal("0.1000"),
        occurred_on=date(2026, 8, 15),
    )
    regular_signup.charge = regular_charge
    regular_signup.save(update_fields=["charge"])

    assert sync_meal_signup_charges_for_camp(camp) == 2

    family_signup.refresh_from_db()
    family_charge.refresh_from_db()
    regular_signup.refresh_from_db()
    regular_charge.refresh_from_db()
    assert family_signup.foerdersatz == companion_rule.foerdersatz
    assert regular_signup.foerdersatz == companion_rule.foerdersatz
    assert family_charge.unit_price == regular_charge.unit_price == Decimal("12.00")
    assert family_charge.foerdersatz == regular_charge.foerdersatz == Decimal("1.0000")
    assert family_charge.participant == guardian
    assert family_charge.family_member == family_companion
    family_settlement = calculate_participant_settlement(guardian)
    regular_settlement = calculate_participant_settlement(regular_companion)
    assert family_settlement.total_subsidy == regular_settlement.total_subsidy == Decimal("12.00")
    assert family_settlement.total_due == regular_settlement.total_due == Decimal("0.00")


@pytest.mark.django_db
def test_settlement_protection_matches_exact_snapshot_charge_membership():
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)
    future_charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Zukünftiges Essen",
        quantity=Decimal("1"),
        unit_price=Decimal("12.00"),
        occurred_on=timezone.localdate() + timedelta(days=7),
    )
    undated_charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Essen ohne Datum",
        quantity=Decimal("1"),
        unit_price=Decimal("8.00"),
        occurred_on=None,
    )
    excluded_charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Vor Snapshot gelöscht",
        quantity=Decimal("1"),
        unit_price=Decimal("9.00"),
        occurred_on=timezone.localdate(),
        deleted_at=timezone.now(),
    )
    create_settlement_run(camp, None)

    assert is_charge_covered_by_settlement_run(future_charge) is True
    assert is_charge_covered_by_settlement_run(undated_charge) is True
    assert is_charge_covered_by_settlement_run(excluded_charge) is False

    later_charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Nach erstem Snapshot",
        quantity=Decimal("1"),
        unit_price=Decimal("7.00"),
        occurred_on=None,
    )
    assert is_charge_covered_by_settlement_run(later_charge) is False

    create_settlement_run(camp, None)
    assert is_charge_covered_by_settlement_run(later_charge) is True


@pytest.mark.django_db
def test_sync_protects_future_and_undated_charges_present_in_settlement_snapshot(monkeypatch):
    monkeypatch.setattr(
        "billing.services.timezone.localdate",
        lambda value=None, timezone=None: date(2026, 8, 14),
    )
    camp = CampFactory(is_active=True)
    rule = _create_dinner_rule(camp, foerdersatz=Decimal("0.1000"), is_default=True)
    future_signup, future_charge = _create_meal_signup_with_charge(camp, meal_date=date(2026, 8, 15))
    undated_signup, undated_charge = _create_meal_signup_with_charge(camp, meal_date=date(2026, 8, 16))
    undated_charge.occurred_on = None
    undated_charge.save(update_fields=["occurred_on"])
    run = create_settlement_run(camp, None)
    original_snapshot = run.settlements.get(participant=future_signup.participant).data
    rule.foerdersatz = Decimal("0.8000")
    rule.unit_price = Decimal("20.00")
    rule.save(update_fields=["foerdersatz", "unit_price"])

    assert sync_meal_signup_charges_for_camp(camp) == 0

    for signup, charge in ((future_signup, future_charge), (undated_signup, undated_charge)):
        signup.refresh_from_db()
        charge.refresh_from_db()
        assert signup.foerdersatz == Decimal("0.1000")
        assert charge.foerdersatz == Decimal("0.1000")
        assert charge.unit_price == Decimal("10.00")
    assert run.settlements.get(participant=future_signup.participant).data == original_snapshot


@pytest.mark.django_db
def test_sync_charge_only_update_is_idempotent(monkeypatch):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 8, 14))
    camp = CampFactory(is_active=True)
    _create_dinner_rule(
        camp,
        foerdersatz=Decimal("0.8000"),
        unit_price=Decimal("20.00"),
        is_default=True,
    )
    signup, charge = _create_meal_signup_with_charge(
        camp,
        meal_date=date(2026, 8, 15),
        foerdersatz=Decimal("0.8000"),
    )

    assert sync_meal_signup_charges_for_camp(camp) == 0
    charge.refresh_from_db()
    first_updated_at = charge.updated_at
    assert charge.foerdersatz == Decimal("0.8000")
    assert charge.unit_price == Decimal("20.00")

    assert sync_meal_signup_charges_for_camp(camp) == 0
    charge.refresh_from_db()
    assert charge.updated_at == first_updated_at
