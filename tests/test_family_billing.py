import csv
from datetime import date
from decimal import Decimal
from importlib import import_module
from io import BytesIO, StringIO

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from billing.forms import ParticipantFamilyMemberForm
from billing.models import AttendanceDay, Charge, KioskActionAuditLog, MealSignup, PriceRule
from billing.permissions import EDITOR_GROUP
from billing.services import (
    calculate_camp_settlements,
    calculate_participant_settlement,
    calculate_participant_settlements,
    charge_audit_snapshot,
    create_booking_delete_audit_log,
    create_settlement_run,
    get_cost_center_evaluation,
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
    ParticipantFamilyMemberFactory(
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
        (companion.full_name, Decimal("250.00")),
    }
    assert settlement.total_due == Decimal("250.00")
    assert camp_settlement[0].total_due == settlement.total_due
    cost_center = get_cost_center_evaluation(camp)["camp_flat"]
    assert cost_center["income"] == Decimal("250.00")
    assert cost_center["income_count"] == 1
    run = create_settlement_run(camp, SuperUserFactory())
    snapshot = run.settlements.get().data
    assert [line["target_name"] for line in snapshot["lines"] if line["target_name"]] == [companion.full_name]
    assert run.total_due == Decimal("250.00")


@pytest.mark.django_db
def test_family_companion_uses_seven_and_eight_night_boundaries_and_guardian_fallback():
    camp = CampFactory()
    guardian = ParticipantFactory(camp=camp, booked_nights=8)
    seven_nights = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role="companion",
        first_name="Sieben",
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 8),
    )
    eight_nights = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role="companion",
        first_name="Acht",
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 9),
    )
    fallback = ParticipantFamilyMemberFactory(guardian=guardian, role="companion", first_name="Fallback")
    for duration, price in (
        (PriceRule.CampFlatDuration.ONE_WEEK, Decimal("100.00")),
        (PriceRule.CampFlatDuration.TWO_WEEKS, Decimal("200.00")),
    ):
        PriceRuleFactory(
            camp=camp,
            kind=PriceRule.Kind.CAMP_FLAT,
            camp_flat_role=PriceRule.CampFlatRole.COMPANION,
            camp_flat_duration=duration,
            unit_price=price,
            is_default=True,
        )

    lines = [line for line in calculate_participant_settlement(guardian).lines if line.target_name]

    assert {(line.target_name, line.unit_price) for line in lines} == {
        (seven_nights.full_name, Decimal("100.00")),
        (eight_nights.full_name, Decimal("200.00")),
        (fallback.full_name, Decimal("200.00")),
    }


@pytest.mark.django_db
def test_family_child_and_inactive_members_do_not_create_automatic_fee():
    guardian = ParticipantFactory()
    active_child = ParticipantFamilyMemberFactory(guardian=guardian, first_name="Aktiv", role="child")
    inactive_companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        first_name="Inaktiv",
        role="companion",
        is_active=False,
    )
    PriceRuleFactory(
        camp=guardian.camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        camp_flat_role=PriceRule.CampFlatRole.PARTICIPANT,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        unit_price=Decimal("100.00"),
        is_default=True,
    )
    PriceRuleFactory(
        camp=guardian.camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        camp_flat_role=PriceRule.CampFlatRole.COMPANION,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        unit_price=Decimal("200.00"),
        is_default=True,
    )

    lines = [line for line in calculate_participant_settlement(guardian).lines if line.target_name]

    assert lines == []
    assert active_child.full_name not in {line.target_name for line in lines}
    assert inactive_companion.full_name not in {line.target_name for line in lines}


@pytest.mark.django_db
def test_family_companion_subsidy_uses_guardian_factors_and_price_rule_rate():
    guardian = ParticipantFactory(
        is_youth_group=True,
        hilfssatz=Decimal("0.5000"),
        berufssatz=Decimal("0.5000"),
    )
    companion = ParticipantFamilyMemberFactory(guardian=guardian, role="companion")
    PriceRuleFactory(
        camp=guardian.camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        camp_flat_role=PriceRule.CampFlatRole.COMPANION,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        unit_price=Decimal("200.00"),
        foerdersatz=Decimal("0.4000"),
        is_default=True,
    )

    line = next(line for line in calculate_participant_settlement(guardian).lines if line.target_name)

    assert line.target_name == companion.full_name
    assert line.gross_total == Decimal("200.00")
    assert line.subsidy_amount == Decimal("20.00")
    assert line.total == Decimal("180.00")


@pytest.mark.django_db
def test_youth_family_child_has_no_camp_fee_but_full_rule_subsidy_on_target_charge():
    guardian = ParticipantFactory(is_youth_group=False)
    child = ParticipantFamilyMemberFactory(guardian=guardian, role="child", is_youth_group=True)
    charge = ChargeFactory(
        participant=guardian,
        family_member=child,
        kind=Charge.Kind.FOOD,
        unit_price=Decimal("100.00"),
        foerdersatz=Decimal("0.4000"),
    )
    MealSignup.objects.create(
        participant=guardian,
        family_member=child,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL_CHILD,
        charge=charge,
    )

    result = calculate_participant_settlement(guardian)

    assert not [line for line in result.lines if line.target_name and line.source.startswith("price_rule:family:")]
    charge_line = next(line for line in result.lines if line.target_name == child.full_name)
    assert charge_line.subsidy_amount == Decimal("40.00")
    assert charge_line.total == Decimal("60.00")


@pytest.mark.django_db
def test_non_youth_family_child_has_no_camp_fee_or_full_youth_subsidy():
    guardian = ParticipantFactory(is_youth_group=False)
    child = ParticipantFamilyMemberFactory(guardian=guardian, role="child", is_youth_group=False)
    ChargeFactory(
        participant=guardian,
        family_member=child,
        kind=Charge.Kind.FOOD,
        unit_price=Decimal("100.00"),
        foerdersatz=Decimal("0.4000"),
    )

    result = calculate_participant_settlement(guardian)

    assert not [line for line in result.lines if line.source.startswith("price_rule:family:")]
    charge_line = next(line for line in result.lines if line.target_name == child.full_name)
    assert charge_line.subsidy_amount == Decimal("0.00")
    assert charge_line.total == Decimal("100.00")


@pytest.mark.django_db
def test_youth_family_companion_gets_duration_fee_and_full_rule_subsidy():
    guardian = ParticipantFactory(is_youth_group=False)
    companion = ParticipantFamilyMemberFactory(guardian=guardian, role="companion", is_youth_group=True)
    PriceRuleFactory(
        camp=guardian.camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        camp_flat_role=PriceRule.CampFlatRole.COMPANION,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        unit_price=Decimal("200.00"),
        foerdersatz=Decimal("0.4000"),
        is_default=True,
    )

    line = next(line for line in calculate_participant_settlement(guardian).lines if line.target_name)

    assert line.target_name == companion.full_name
    assert line.gross_total == Decimal("200.00")
    assert line.subsidy_amount == Decimal("80.00")
    assert line.total == Decimal("120.00")


@pytest.mark.django_db
def test_guardian_own_charge_keeps_guardian_subsidy_factors():
    guardian = ParticipantFactory(
        is_youth_group=True,
        hilfssatz=Decimal("0.5000"),
        berufssatz=Decimal("0.5000"),
    )
    ChargeFactory(
        participant=guardian,
        kind=Charge.Kind.FOOD,
        unit_price=Decimal("100.00"),
        foerdersatz=Decimal("0.4000"),
    )

    line = next(line for line in calculate_participant_settlement(guardian).lines if not line.target_name)

    assert line.subsidy_amount == Decimal("10.00")
    assert line.total == Decimal("90.00")


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["child", "companion"])
def test_family_member_youth_group_is_editable_with_confirmation_and_invalid_post_is_rejected(client, role):
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian, role=role, is_youth_group=False)
    admin = SuperUserFactory()
    client.force_login(admin)

    form = ParticipantFamilyMemberForm(
        {"first_name": member.first_name, "last_name": member.last_name, "role": member.role, "is_youth_group": "on"},
        instance=member,
    )
    assert form.is_valid()

    response = client.post(
        reverse("participant-family-member-edit", args=[guardian.pk, member.pk]),
        {
            "first_name": member.first_name,
            "last_name": member.last_name,
            "role": member.role,
            "is_youth_group": "on",
            "is_active": "on",
        },
    )
    assert response.status_code == 200
    member.refresh_from_db()
    assert member.is_youth_group is False

    response = client.post(
        reverse("participant-family-member-edit", args=[guardian.pk, member.pk]),
        {
            "first_name": member.first_name,
            "last_name": member.last_name,
            "role": member.role,
            "is_youth_group": "on",
            "confirm_settlement_change": "1",
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    member.refresh_from_db()
    assert member.is_youth_group is True


@pytest.mark.django_db
def test_family_companion_without_guardian_funding_eligibility_has_no_subsidy():
    guardian = ParticipantFactory(is_youth_group=False)
    ParticipantFamilyMemberFactory(guardian=guardian, role="companion")
    PriceRuleFactory(
        camp=guardian.camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        camp_flat_role=PriceRule.CampFlatRole.COMPANION,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        unit_price=Decimal("200.00"),
        foerdersatz=Decimal("1.0000"),
        is_default=True,
    )

    line = next(line for line in calculate_participant_settlement(guardian).lines if line.target_name)

    assert line.subsidy_amount == Decimal("0.00")
    assert line.total == Decimal("200.00")


@pytest.mark.django_db
def test_inactive_family_members_receive_no_new_automatic_fee_but_snapshots_remain_readable():
    camp = CampFactory()
    guardian = ParticipantFactory(camp=camp, actual_nights=3)
    member = ParticipantFamilyMemberFactory(
        guardian=guardian,
        first_name="Archiv",
        role="companion",
        is_active=True,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Teilnehmer 1 Woche",
        unit_price=Decimal("100.00"),
        camp_flat_role=PriceRule.CampFlatRole.COMPANION,
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

    with django_assert_num_queries(9):
        results = calculate_participant_settlements(guardians)

    assert {line.target_name for result in results.values() for line in result.lines} == {
        member.full_name for member in members
    }


@pytest.mark.django_db
def test_tracked_attendance_keeps_batch_settlements_query_bounded(django_assert_num_queries):
    """Attendance rows are loaded once per target type, not once per person or price rule."""
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    PriceRuleFactory(camp=camp, kind=PriceRule.Kind.NIGHT, is_default=True)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        camp_flat_role=PriceRule.CampFlatRole.PARTICIPANT,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        is_default=True,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        camp_flat_role=PriceRule.CampFlatRole.COMPANION,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        applies_to_adults=False,
        is_default=True,
    )
    guardians = []
    for _index in range(3):
        guardian = ParticipantFactory(
            camp=camp,
            arrival_date=date(2026, 7, 1),
            departure_date=date(2026, 7, 3),
            attendance_tracking_enabled=True,
        )
        companion = ParticipantFamilyMemberFactory(
            guardian=guardian,
            role=ParticipantFamilyMemberFactory._meta.model.Role.COMPANION,
            arrival_date=date(2026, 7, 1),
            departure_date=date(2026, 7, 3),
            attendance_tracking_enabled=True,
        )
        AttendanceDay.objects.create(participant=guardian, date=date(2026, 7, 2), is_present=True)
        AttendanceDay.objects.create(
            participant=guardian,
            family_member=companion,
            date=date(2026, 7, 2),
            is_present=True,
        )
        guardians.append(guardian)

    with django_assert_num_queries(11):
        results = calculate_participant_settlements(guardians)

    assert {result.participant.pk for result in results.values()} == {guardian.pk for guardian in guardians}
    assert {
        line.quantity for result in results.values() for line in result.lines if line.source.startswith("price_rule:")
    } == {Decimal("1")}


@pytest.mark.django_db
def test_tracked_family_attendance_is_prefetched_for_single_settlement():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        camp_flat_role=PriceRule.CampFlatRole.COMPANION,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        is_default=True,
    )
    guardian = ParticipantFactory(camp=camp)
    for index in range(3):
        companion = ParticipantFamilyMemberFactory(
            guardian=guardian,
            role="companion",
            arrival_date=date(2026, 7, 1),
            departure_date=date(2026, 7, 6),
            attendance_tracking_enabled=True,
        )
        AttendanceDay.objects.create(
            participant=guardian,
            family_member=companion,
            date=date(2026, 7, index + 1),
            is_present=True,
        )

    with CaptureQueriesContext(connection) as queries:
        settlement = calculate_participant_settlement(guardian)

    attendance_queries = [query for query in queries if "billing_attendanceday" in query["sql"]]
    assert len(attendance_queries) == 1
    assert len([line for line in settlement.lines if line.source.startswith("price_rule:family:")]) == 3


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


@pytest.mark.django_db
def test_charge_create_accepts_the_guardians_family_member_and_rejects_foreign_target(client):
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian)
    foreign_member = ParticipantFamilyMemberFactory(guardian=ParticipantFactory(camp=guardian.camp))
    client.force_login(SuperUserFactory())
    url = reverse("charge-create", args=[guardian.pk])
    data = {
        "kind": Charge.Kind.OTHER,
        "description": "Familienkosten",
        "quantity": "1",
        "unit_price": "10.00",
        "foerdersatz": "0",
        "occurred_on": "",
    }

    accepted = client.post(url, {**data, "family_member": member.pk})
    rejected = client.post(url, {**data, "family_member": foreign_member.pk})

    assert accepted.status_code == 302
    assert Charge.objects.get(description="Familienkosten").family_member == member
    assert rejected.status_code == 200
    assert Charge.objects.filter(family_member=foreign_member).count() == 0


@pytest.mark.django_db
def test_family_member_financial_edit_requires_confirmation_but_name_edit_does_not(client):
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian, arrival_date=date(2026, 7, 1))
    client.force_login(SuperUserFactory())
    url = reverse("participant-family-member-edit", args=[guardian.pk, member.pk])
    data = {
        "first_name": member.first_name,
        "last_name": member.last_name,
        "role": member.role,
        "arrival_date": "2026-07-02",
        "departure_date": "",
        "is_active": "on",
    }

    confirmation = client.post(url, data)
    member.refresh_from_db()
    name_edit = client.post(url, {**data, "arrival_date": "2026-07-01", "first_name": "Neu"})

    assert confirmation.status_code == 200
    assert b"Abrechnung" in confirmation.content
    assert member.arrival_date == date(2026, 7, 1)
    assert name_edit.status_code == 302
    member.refresh_from_db()
    assert member.first_name == "Neu"


@pytest.mark.django_db
def test_family_member_financial_edit_persists_only_after_explicit_confirmation(client):
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian, is_active=True)
    client.force_login(SuperUserFactory())
    url = reverse("participant-family-member-edit", args=[guardian.pk, member.pk])
    data = {
        "first_name": member.first_name,
        "last_name": member.last_name,
        "role": member.role,
        "arrival_date": "",
        "departure_date": "",
    }

    response = client.post(url, {**data, "confirm_settlement_change": "1"})

    assert response.status_code == 302
    member.refresh_from_db()
    assert member.is_active is False


@pytest.mark.django_db
def test_family_member_role_edit_requires_confirmation_before_persisting(client):
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian, role="child")
    client.force_login(SuperUserFactory())
    url = reverse("participant-family-member-edit", args=[guardian.pk, member.pk])
    data = {
        "first_name": member.first_name,
        "last_name": member.last_name,
        "role": "companion",
        "arrival_date": "",
        "departure_date": "",
        "is_active": "on",
    }

    confirmation = client.post(url, data)

    member.refresh_from_db()
    assert confirmation.status_code == 200
    assert b"Abrechnung" in confirmation.content
    assert member.role == "child"

    confirmed = client.post(url, {**data, "confirm_settlement_change": "1"})

    assert confirmed.status_code == 302
    member.refresh_from_db()
    assert member.role == "companion"


@pytest.mark.django_db
def test_family_member_combined_settlement_changes_use_one_confirmation(client):
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role="child",
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 5),
        is_active=True,
    )
    client.force_login(SuperUserFactory())
    url = reverse("participant-family-member-edit", args=[guardian.pk, member.pk])
    data = {
        "first_name": member.first_name,
        "last_name": member.last_name,
        "role": "companion",
        "arrival_date": "2026-07-02",
        "departure_date": "2026-07-07",
    }

    confirmation = client.post(url, data)

    member.refresh_from_db()
    assert confirmation.status_code == 200
    assert (member.role, member.arrival_date, member.departure_date, member.is_active) == (
        "child",
        date(2026, 7, 1),
        date(2026, 7, 5),
        True,
    )

    confirmed = client.post(url, {**data, "confirm_settlement_change": "1"})

    assert confirmed.status_code == 302
    member.refresh_from_db()
    assert (member.role, member.arrival_date, member.departure_date, member.is_active) == (
        "companion",
        date(2026, 7, 2),
        date(2026, 7, 7),
        False,
    )


@pytest.mark.django_db
def test_family_member_edit_rejects_invalid_and_csrf_missing_financial_updates(client):
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian, is_active=True)
    admin = SuperUserFactory()
    client.force_login(admin)
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin)
    url = reverse("participant-family-member-edit", args=[guardian.pk, member.pk])

    invalid = client.post(url, {"first_name": "Neu"})
    csrf_rejected = csrf_client.post(
        url,
        {
            "first_name": member.first_name,
            "last_name": member.last_name,
            "role": member.role,
            "arrival_date": "",
            "departure_date": "",
            "confirm_settlement_change": "1",
        },
    )

    member.refresh_from_db()
    assert invalid.status_code == 200
    assert csrf_rejected.status_code == 403
    assert member.is_active is True


@pytest.mark.django_db
def test_participant_detail_renders_immutable_family_audit_target_name(client):
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian, first_name="Alt")
    audit = KioskActionAuditLog.objects.create(
        camp=guardian.camp,
        actor_participant=guardian,
        target_participant=guardian,
        target_family_member=member,
        action=KioskActionAuditLog.Action.MEAL_BOOKED,
        description="Essensanmeldung gespeichert.",
    )
    member.first_name = "Neu"
    member.save(update_fields=["first_name", "updated_at"])
    client.force_login(SuperUserFactory())

    response = client.get(reverse("participant-detail", args=[guardian.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert f"{audit.target_display_name} – Essensanmeldung gespeichert." in content
    assert f"{member.full_name} – Essensanmeldung gespeichert." not in content
