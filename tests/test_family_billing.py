import csv
from datetime import date
from decimal import Decimal
from importlib import import_module
from io import BytesIO, StringIO

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from billing.models import Charge, KioskActionAuditLog, MealSignup, PriceRule
from billing.permissions import EDITOR_GROUP
from billing.services import (
    calculate_camp_settlements,
    calculate_participant_settlement,
    calculate_participant_settlements,
    charge_audit_snapshot,
    create_booking_delete_audit_log,
    create_settlement_run,
    restore_booking_from_audit_log,
)
from tests.factories import (
    CampFactory,
    ChargeFactory,
    GroupFactory,
    ParticipantFactory,
    ParticipantFamilyMemberFactory,
    PriceRuleFactory,
    SuperUserFactory,
    UserFactory,
)


@pytest.mark.django_db
def test_family_charge_requires_a_member_of_its_guardian_account():
    guardian = ParticipantFactory()
    unrelated_member = ParticipantFamilyMemberFactory(guardian=ParticipantFactory(camp=guardian.camp))
    charge = ChargeFactory(participant=guardian, family_member=unrelated_member)

    with pytest.raises(ValidationError, match="Zielmitglied"):
        charge.full_clean()


@pytest.mark.django_db
def test_family_camp_fees_are_attributed_once_to_the_guardian_for_stay_and_role():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    guardian = ParticipantFactory(camp=camp, actual_nights=10)
    child = ParticipantFamilyMemberFactory(
        guardian=guardian,
        first_name="Kind",
        role="child",
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 6),
    )
    companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        first_name="Begleitung",
        role="companion",
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 11),
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Teilnehmer 1 Woche",
        unit_price=Decimal("100.00"),
        camp_flat_role=PriceRule.CampFlatRole.PARTICIPANT,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        is_default=True,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Begleitperson 2 Wochen",
        unit_price=Decimal("250.00"),
        camp_flat_role=PriceRule.CampFlatRole.COMPANION,
        camp_flat_duration=PriceRule.CampFlatDuration.TWO_WEEKS,
        applies_to_adults=False,
        is_default=True,
    )

    settlement = calculate_participant_settlement(guardian)
    camp_settlement = calculate_camp_settlements(camp)

    family_lines = [line for line in settlement.lines if line.target_name]
    assert {(line.target_name, line.total) for line in family_lines} == {
        (child.full_name, Decimal("100.00")),
        (companion.full_name, Decimal("250.00")),
    }
    assert settlement.total_due == Decimal("350.00")
    assert camp_settlement[0].total_due == settlement.total_due


@pytest.mark.django_db
def test_inactive_family_members_receive_no_new_automatic_fee_but_snapshots_remain_readable():
    camp = CampFactory()
    guardian = ParticipantFactory(camp=camp, actual_nights=3)
    member = ParticipantFamilyMemberFactory(guardian=guardian, first_name="Archiv", is_active=True)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Teilnehmer 1 Woche",
        unit_price=Decimal("100.00"),
        camp_flat_role=PriceRule.CampFlatRole.PARTICIPANT,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        is_default=True,
    )
    run = create_settlement_run(camp, SuperUserFactory())
    member.is_active = False
    member.save(update_fields=["is_active", "updated_at"])

    current = calculate_participant_settlement(guardian)
    historic_line = next(
        line for line in run.settlements.get().data["lines"] if line["target_name"] == member.full_name
    )

    assert not [line for line in current.lines if line.target_name == member.full_name]
    assert historic_line["target_name"] == member.full_name


@pytest.mark.django_db
def test_family_target_survives_charge_audit_and_settlement_snapshot_round_trip():
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian, first_name="Mara")
    charge = ChargeFactory(participant=guardian, family_member=member, description="Abendessen")

    audit_snapshot = charge_audit_snapshot(charge)
    run = create_settlement_run(guardian.camp, SuperUserFactory())
    settlement_line = run.settlements.get().data["lines"][0]

    assert audit_snapshot["family_member"] == member.full_name
    assert settlement_line["target_name"] == member.full_name
    assert settlement_line["booking_references"] == [charge.booking_reference]


@pytest.mark.django_db
def test_family_target_survives_soft_delete_and_restore_in_guardian_audit_context():
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian, first_name="Wiederherstellen")
    charge = ChargeFactory(participant=guardian, family_member=member)
    admin = SuperUserFactory()
    audit = create_booking_delete_audit_log(charge, charge_audit_snapshot(charge), admin)

    charge.deleted_at = timezone.now()
    charge.deleted_by = admin
    charge.save(update_fields=["deleted_at", "deleted_by"])
    restored = restore_booking_from_audit_log(audit, admin)

    restored.refresh_from_db()
    assert restored.participant == guardian
    assert restored.family_member == member
    assert audit.before["family_member"] == member.full_name


@pytest.mark.django_db
def test_editor_can_view_family_billing_but_only_admin_can_edit_family_member(client):
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian, first_name="Sichtbar")
    editor = UserFactory()
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    client.force_login(editor)

    detail = client.get(reverse("participant-detail", args=[guardian.pk]))
    edit = client.get(reverse("participant-family-member-edit", args=[guardian.pk, member.pk]))

    assert detail.status_code == 200
    assert member.full_name.encode() in detail.content
    assert edit.status_code == 302


@pytest.mark.django_db
def test_family_member_edit_rejects_ownership_tampering(client):
    guardian = ParticipantFactory()
    foreign_member = ParticipantFamilyMemberFactory(guardian=ParticipantFactory(camp=guardian.camp))
    client.force_login(SuperUserFactory())

    response = client.post(
        reverse("participant-family-member-edit", args=[guardian.pk, foreign_member.pk]),
        {"first_name": "Manipuliert", "last_name": "Muster", "role": "child", "is_active": "on"},
    )

    assert response.status_code == 404
    foreign_member.refresh_from_db()
    assert foreign_member.first_name != "Manipuliert"


@pytest.mark.django_db
def test_family_charges_and_meal_signups_are_query_bounded_and_visible_in_guardian_context(
    django_assert_num_queries,
):
    camp = CampFactory()
    guardians = [ParticipantFactory(camp=camp) for _ in range(2)]
    members = []
    for guardian in guardians:
        member = ParticipantFamilyMemberFactory(guardian=guardian)
        members.append(member)
        charge = ChargeFactory(participant=guardian, family_member=member)
        MealSignup.objects.create(
            participant=guardian,
            family_member=member,
            meal_date=date(2026, 7, 2),
            meal=MealSignup.Meal.DINNER,
            variant=MealSignup.Variant.NORMAL_CHILD,
            charge=charge,
        )

    with django_assert_num_queries(8):
        results = calculate_participant_settlements(guardians)

    assert {line.target_name for result in results.values() for line in result.lines} == {
        member.full_name for member in members
    }


@pytest.mark.django_db
def test_family_meal_charge_is_attributed_to_its_target_and_audit_context():
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian)
    charge = ChargeFactory(participant=guardian, family_member=member, kind=Charge.Kind.FOOD)
    signup = MealSignup.objects.create(
        participant=guardian,
        family_member=member,
        meal_date=date(2026, 7, 2),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL_CHILD,
        charge=charge,
    )
    audit = KioskActionAuditLog.objects.create(
        camp=guardian.camp,
        actor_participant=guardian,
        target_participant=guardian,
        target_family_member=member,
        charge=charge,
        action=KioskActionAuditLog.Action.MEAL_BOOKED,
        description="Essensanmeldung gespeichert.",
    )

    assert signup.charge.family_member == member
    assert audit.charge.family_member == audit.target_family_member


@pytest.mark.django_db
def test_charge_target_backfill_assigns_only_unambiguous_family_meal_history():
    migration = import_module("billing.migrations.0058_charge_family_member_attribution")
    guardian = ParticipantFactory()
    child = ParticipantFamilyMemberFactory(guardian=guardian)
    companion = ParticipantFamilyMemberFactory(guardian=guardian, role="companion")
    unique_charge = ChargeFactory(participant=guardian, kind=Charge.Kind.FOOD)
    ambiguous_charge = ChargeFactory(participant=guardian, kind=Charge.Kind.FOOD)
    for target, charge, meal, meal_date in (
        (child, unique_charge, MealSignup.Meal.BREAKFAST, date(2026, 7, 3)),
        (child, ambiguous_charge, MealSignup.Meal.BREAKFAST, date(2026, 7, 4)),
        (companion, ambiguous_charge, MealSignup.Meal.DINNER, date(2026, 7, 4)),
    ):
        MealSignup.objects.create(
            participant=guardian,
            family_member=target,
            meal_date=meal_date,
            meal=meal,
            variant=MealSignup.Variant.NORMAL_CHILD,
            charge=charge,
        )

    migration.backfill_charge_family_members(apps, None)
    migration.backfill_charge_family_members(apps, None)

    unique_charge.refresh_from_db()
    ambiguous_charge.refresh_from_db()
    assert unique_charge.family_member == child
    assert ambiguous_charge.family_member is None


@pytest.mark.django_db
def test_family_target_is_preserved_in_current_csv_xlsx_and_pdf_exports(client, monkeypatch):
    guardian = ParticipantFactory(first_name="Jan", last_name="Guardian")
    member = ParticipantFamilyMemberFactory(guardian=guardian, first_name="Mila", last_name="Familie")
    ChargeFactory(participant=guardian, family_member=member, description="Familienbuchung")
    client.force_login(SuperUserFactory())

    csv_response = client.get(reverse("export-settlements-csv", args=[guardian.camp_id]))
    workbook_response = client.get(reverse("export-workbook", args=[guardian.camp_id]))
    csv_rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8"))))

    assert csv_rows[0][2] == "Familienziele"
    assert csv_rows[1][2] == member.full_name
    workbook = load_workbook(BytesIO(workbook_response.content), data_only=True)
    assert workbook["Abrechnung"]["C2"].value == member.full_name

    drawn_labels = []

    class PdfCanvas:
        def __init__(self, *_args, **_kwargs):
            pass

        def drawString(self, _x, _y, text):
            drawn_labels.append(text)

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

        def getPageNumber(self):
            return 1

    monkeypatch.setattr("billing.exporters.canvas.Canvas", PdfCanvas)
    client.get(reverse("export-participant-pdf", args=[guardian.pk]))

    assert f"Familienbuchung für {member.full_name}" in drawn_labels


@pytest.mark.django_db
def test_charge_edit_rejects_a_target_from_another_guardian(client):
    guardian = ParticipantFactory()
    charge = ChargeFactory(participant=guardian)
    foreign_member = ParticipantFamilyMemberFactory(guardian=ParticipantFactory(camp=guardian.camp))
    client.force_login(SuperUserFactory())

    response = client.post(
        reverse("charge-edit", args=[charge.pk]),
        {
            "kind": Charge.Kind.OTHER,
            "description": charge.description,
            "family_member": foreign_member.pk,
            "quantity": "1",
            "unit_price": "10.00",
            "foerdersatz": "0",
            "occurred_on": "",
        },
    )

    assert response.status_code == 200
    charge.refresh_from_db()
    assert charge.family_member is None
