import importlib
from decimal import Decimal
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test.utils import CaptureQueriesContext

from billing.models import BookingAuditLog, Charge, ParticipantBookingLink
from tests.factories import ChargeFactory, ParticipantFactory, UserFactory

migration = importlib.import_module("billing.migrations.0013_remove_legacy_charge_cancellation_columns")
partner_authorization_migration = importlib.import_module("billing.migrations.0046_kiosk_action_audit_log")
booking_link_permissions_migration = importlib.import_module(
    "billing.migrations.0051_remove_booking_link_mutation_permissions"
)

CREDIT_PAYOUT_OLD_TARGET = [("billing", "0066_credit_payout")]
CREDIT_PAYOUT_NEW_TARGET = [("billing", "0067_positive_credit_payout_amount")]
POSITION_REPORT_OLD_TARGET = CREDIT_PAYOUT_NEW_TARGET
POSITION_REPORT_NEW_TARGET = [("billing", "0068_charge_position_report_description")]


def _create_historical_credit_payouts(historical_apps, amounts: list[Decimal]):
    User = historical_apps.get_model("auth", "User")
    Camp = historical_apps.get_model("billing", "Camp")
    Participant = historical_apps.get_model("billing", "Participant")
    CreditPayout = historical_apps.get_model("billing", "CreditPayout")
    user = User.objects.create(username="private-migration-operator")
    camp = Camp.objects.create(name="Private Migration Camp", year=2040)
    participant = Participant.objects.create(camp=camp, first_name="Private", last_name="Participant")
    return [
        CreditPayout.objects.create(
            participant=participant,
            amount=amount,
            method="cash",
            created_by=user,
            idempotency_key=uuid4(),
        )
        for amount in amounts
    ]


def _restore_current_migration_state() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def charge_columns() -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, Charge._meta.db_table)
    return {column.name for column in description}


@pytest.mark.django_db(transaction=True)
def test_legacy_charge_cancellation_columns_are_migrated_and_removed() -> None:
    charge = ChargeFactory(unit_price=Decimal("12.50"))
    user = UserFactory()
    audit_log = BookingAuditLog.objects.create(
        participant=charge.participant,
        charge=charge,
        changed_by=user,
        action="cancelled",
        before={},
        after={},
    )
    table = connection.ops.quote_name(Charge._meta.db_table)

    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN cancellation_note TEXT NOT NULL DEFAULT ''")
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN cancelled_at datetime NULL")
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN cancelled_by_id INTEGER NULL")
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN is_cancelled bool NOT NULL DEFAULT 0")
        cursor.execute(
            f"UPDATE {table} SET cancellation_note = %s, cancelled_at = %s, cancelled_by_id = %s, "
            "is_cancelled = %s WHERE id = %s",
            ["Legacy-Storno", "2026-06-03 15:00:00", user.pk, True, charge.pk],
        )

    with connection.schema_editor() as schema_editor:
        migration.remove_legacy_charge_cancellation_columns(apps, schema_editor)

    charge.refresh_from_db()
    audit_log.refresh_from_db()
    assert charge.deleted_at is not None
    assert charge.deleted_by == user
    assert audit_log.action == BookingAuditLog.Action.DELETED
    assert not set(migration.LEGACY_CHARGE_COLUMNS) & charge_columns()

    Charge.objects.create(
        participant=charge.participant,
        kind=Charge.Kind.DRINK,
        description="Getränk",
        quantity=1,
        unit_price=Decimal("2.50"),
    )


@pytest.mark.django_db(transaction=True)
def test_legacy_charge_cleanup_is_a_noop_for_current_schema() -> None:
    before = charge_columns()

    with connection.schema_editor() as schema_editor:
        migration.remove_legacy_charge_cancellation_columns(apps, schema_editor)

    assert charge_columns() == before


@pytest.mark.django_db(transaction=True)
def test_legacy_charge_cleanup_removes_a_partial_legacy_schema() -> None:
    table = connection.ops.quote_name(Charge._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN cancellation_note TEXT NULL")

    with connection.schema_editor() as schema_editor:
        migration.remove_legacy_charge_cancellation_columns(apps, schema_editor)

    assert "cancellation_note" not in charge_columns()


@pytest.mark.django_db(transaction=True)
def test_price_element_subsidy_migration_preserves_existing_camp_rate() -> None:
    executor = MigrationExecutor(connection)
    old_target = [("billing", "0013_remove_legacy_charge_cancellation_columns")]
    executor.migrate(old_target)
    old_apps = executor.loader.project_state(old_target).apps

    Camp = old_apps.get_model("billing", "Camp")
    Participant = old_apps.get_model("billing", "Participant")
    PriceRule = old_apps.get_model("billing", "PriceRule")
    OldCharge = old_apps.get_model("billing", "Charge")
    camp = Camp.objects.create(name="Migration", year=2030, foerdersatz=Decimal("0.4000"))
    participant = Participant.objects.create(camp=camp, first_name="Mia", last_name="Migration")
    eligible_rule = PriceRule.objects.create(
        camp=camp,
        kind="drink",
        name="Getränk",
        unit_price=Decimal("2.50"),
        foerderfaehig=True,
    )
    ineligible_charge = OldCharge.objects.create(
        participant=participant,
        kind="other",
        description="Ohne Förderung",
        unit_price=Decimal("5.00"),
        foerderfaehig=False,
    )

    new_target = [("billing", "0014_subsidy_rate_per_price_element")]
    executor = MigrationExecutor(connection)
    executor.migrate(new_target)
    new_apps = executor.loader.project_state(new_target).apps

    NewPriceRule = new_apps.get_model("billing", "PriceRule")
    NewCharge = new_apps.get_model("billing", "Charge")
    assert NewPriceRule.objects.get(pk=eligible_rule.pk).foerdersatz == Decimal("0.4000")
    assert NewCharge.objects.get(pk=ineligible_charge.pk).foerdersatz == Decimal("0")


@pytest.mark.django_db
def test_partner_authorization_migration_requires_fresh_invitation_and_acceptance() -> None:
    inviter = ParticipantFactory()
    invitee = ParticipantFactory(camp=inviter.camp)
    legacy_accepted = ParticipantBookingLink.objects.create(
        inviter=inviter,
        invitee=invitee,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    pending = ParticipantBookingLink.objects.create(
        inviter=invitee,
        invitee=inviter,
        status=ParticipantBookingLink.Status.PENDING,
    )
    revoked = ParticipantBookingLink.objects.create(
        inviter=inviter,
        invitee=ParticipantFactory(camp=inviter.camp),
        status=ParticipantBookingLink.Status.REVOKED,
    )

    partner_authorization_migration.require_fresh_partner_authorization(apps, None)

    legacy_accepted.refresh_from_db()
    pending.refresh_from_db()
    revoked.refresh_from_db()
    assert legacy_accepted.status == ParticipantBookingLink.Status.REVOKED
    assert pending.status == ParticipantBookingLink.Status.REVOKED
    assert revoked.status == ParticipantBookingLink.Status.REVOKED


@pytest.mark.django_db
def test_booking_link_permissions_migration_removes_existing_role_mutation_rights() -> None:
    group_model = apps.get_model("auth", "Group")
    permission_model = apps.get_model("auth", "Permission")
    booking_link_permissions = permission_model.objects.filter(
        content_type__app_label="billing",
        content_type__model="participantbookinglink",
    )
    groups = [group_model.objects.create(name=name) for name in ("Admin", "Bearbeiter")]
    for group in groups:
        group.permissions.set(booking_link_permissions)

    booking_link_permissions_migration.remove_booking_link_mutation_permissions(apps, None)
    booking_link_permissions_migration.remove_booking_link_mutation_permissions(apps, None)

    for group in groups:
        assert set(
            group.permissions.filter(
                content_type__app_label="billing",
                content_type__model="participantbookinglink",
            ).values_list("codename", flat=True)
        ) == {"view_participantbookinglink"}


@pytest.mark.django_db(transaction=True)
def test_kiosk_audit_migration_snapshots_existing_family_member_names() -> None:
    executor = MigrationExecutor(connection)
    old_target = [("billing", "0049_protect_kiosk_audit_family_members")]
    executor.migrate(old_target)
    old_apps = executor.loader.project_state(old_target).apps

    Camp = old_apps.get_model("billing", "Camp")
    Participant = old_apps.get_model("billing", "Participant")
    FamilyMember = old_apps.get_model("billing", "ParticipantFamilyMember")
    AuditLog = old_apps.get_model("billing", "KioskActionAuditLog")
    camp = Camp.objects.create(name="Migration", year=2030, is_active=True)
    participant = Participant.objects.create(camp=camp, first_name="Haupt", last_name="Konto")
    actor = FamilyMember.objects.create(
        guardian=participant,
        first_name="Akteur",
        last_name="Alt",
        role="companion",
    )
    target = FamilyMember.objects.create(
        guardian=participant,
        first_name="Ziel",
        last_name="Alt",
        role="child",
    )
    audit_log = AuditLog.objects.create(
        camp=camp,
        actor_participant=participant,
        actor_family_member=actor,
        target_participant=participant,
        target_family_member=target,
        action="quick_booked",
        description="Schnellbuchung erstellt.",
    )

    new_target = [("billing", "0050_kiosk_audit_display_name_snapshots")]
    executor = MigrationExecutor(connection)
    executor.migrate(new_target)
    new_apps = executor.loader.project_state(new_target).apps

    migrated_audit_log = new_apps.get_model("billing", "KioskActionAuditLog").objects.get(pk=audit_log.pk)
    assert migrated_audit_log.actor_display_name_snapshot == "Akteur Alt"
    assert migrated_audit_log.target_display_name_snapshot == "Ziel Alt"


@pytest.mark.django_db(transaction=True)
def test_family_member_youth_group_migration_defaults_false_and_rolls_back() -> None:
    executor = MigrationExecutor(connection)
    old_target = [("billing", "0058_charge_family_member_attribution")]
    executor.migrate(old_target)
    old_apps = executor.loader.project_state(old_target).apps
    Camp = old_apps.get_model("billing", "Camp")
    Participant = old_apps.get_model("billing", "Participant")
    FamilyMember = old_apps.get_model("billing", "ParticipantFamilyMember")
    camp = Camp.objects.create(name="Migration", year=2030)
    participant = Participant.objects.create(camp=camp, first_name="Haupt", last_name="Konto")
    member = FamilyMember.objects.create(
        guardian=participant,
        first_name="Alt",
        last_name="Kind",
        role="child",
    )

    new_target = [("billing", "0059_participantfamilymember_is_youth_group")]
    executor = MigrationExecutor(connection)
    executor.migrate(new_target)
    new_member = (
        executor.loader.project_state(new_target)
        .apps.get_model("billing", "ParticipantFamilyMember")
        .objects.get(pk=member.pk)
    )
    assert new_member.is_youth_group is False

    executor = MigrationExecutor(connection)
    executor.migrate(old_target)
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, "billing_participantfamilymember")
        }
    assert "is_youth_group" not in columns
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_shift_assignment_migration_preserves_legacy_null_identity() -> None:
    executor = MigrationExecutor(connection)
    old_target = [("billing", "0059_participantfamilymember_is_youth_group")]
    executor.migrate(old_target)
    old_apps = executor.loader.project_state(old_target).apps
    Camp = old_apps.get_model("billing", "Camp")
    Participant = old_apps.get_model("billing", "Participant")
    Shift = old_apps.get_model("billing", "Shift")
    ShiftAssignment = old_apps.get_model("billing", "ShiftAssignment")
    camp = Camp.objects.create(name="Shift Migration", year=2030)
    participant = Participant.objects.create(camp=camp, first_name="Legacy", last_name="Participant")
    shift = Shift.objects.create(camp=camp, name="Legacy Duty", date="2030-07-20")
    assignment = ShiftAssignment.objects.create(shift=shift, participant=participant)

    new_target = [("billing", "0060_shiftassignment_family_member")]
    executor = MigrationExecutor(connection)
    executor.migrate(new_target)
    new_assignment = (
        executor.loader.project_state(new_target)
        .apps.get_model("billing", "ShiftAssignment")
        .objects.get(pk=assignment.pk)
    )

    assert new_assignment.family_member_id is None
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_credit_payout_amount_migration_accepts_valid_historical_boundaries() -> None:
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(CREDIT_PAYOUT_OLD_TARGET)
        old_apps = executor.loader.project_state(CREDIT_PAYOUT_OLD_TARGET).apps
        payouts = _create_historical_credit_payouts(old_apps, [Decimal("0.01"), Decimal("99999999.99")])

        executor = MigrationExecutor(connection)
        executor.migrate(CREDIT_PAYOUT_NEW_TARGET)
        new_apps = executor.loader.project_state(CREDIT_PAYOUT_NEW_TARGET).apps
        migrated_amounts = list(
            new_apps.get_model("billing", "CreditPayout")
            .objects.filter(pk__in=[payout.pk for payout in payouts])
            .order_by("amount")
            .values_list("amount", flat=True)
        )

        assert migrated_amounts == [Decimal("0.01"), Decimal("99999999.99")]
    finally:
        _restore_current_migration_state()


@pytest.mark.django_db(transaction=True)
def test_credit_payout_amount_migration_preflight_rejects_invalid_historical_rows_without_mutation() -> None:
    old_credit_payout = None
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(CREDIT_PAYOUT_OLD_TARGET)
        old_apps = executor.loader.project_state(CREDIT_PAYOUT_OLD_TARGET).apps
        payouts = _create_historical_credit_payouts(old_apps, [Decimal("0.00"), Decimal("-0.01")])
        old_credit_payout = old_apps.get_model("billing", "CreditPayout")

        executor = MigrationExecutor(connection)
        with pytest.raises(RuntimeError) as exc_info:
            executor.migrate(CREDIT_PAYOUT_NEW_TARGET)

        assert str(exc_info.value) == (
            "CreditPayout migration preflight failed: 2 rows violate the amount contract "
            "(0.01 to 99999999.99 with at most 2 decimal places). Clean billing_creditpayout.amount "
            "manually before retrying; no rows were changed."
        )
        assert old_credit_payout.objects.filter(pk__in=[payout.pk for payout in payouts]).count() == 2
        assert set(
            old_credit_payout.objects.filter(pk__in=[payout.pk for payout in payouts]).values_list("amount", flat=True)
        ) == {Decimal("-0.01"), Decimal("0.00")}
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, "billing_creditpayout")
        assert "credit_payout_amount_valid" not in constraints
        assert "Private" not in str(exc_info.value)
    finally:
        if old_credit_payout is not None:
            old_credit_payout.objects.all().delete()
        _restore_current_migration_state()


@pytest.mark.django_db(transaction=True)
def test_credit_payout_amount_migration_preflight_counts_sqlite_subcent_and_oversize_without_mutation() -> None:
    if connection.vendor != "sqlite":
        pytest.skip("SQLite stores subcent values despite DecimalField scale metadata")
    old_credit_payout = None
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(CREDIT_PAYOUT_OLD_TARGET)
        old_apps = executor.loader.project_state(CREDIT_PAYOUT_OLD_TARGET).apps
        payouts = _create_historical_credit_payouts(old_apps, [Decimal("0.011"), Decimal("100000000.00")])
        old_credit_payout = old_apps.get_model("billing", "CreditPayout")

        executor = MigrationExecutor(connection)
        with pytest.raises(RuntimeError, match="preflight failed: 2 rows"):
            executor.migrate(CREDIT_PAYOUT_NEW_TARGET)

        assert old_credit_payout.objects.filter(pk__in=[payout.pk for payout in payouts]).count() == 2
    finally:
        if old_credit_payout is not None:
            old_credit_payout.objects.all().delete()
        _restore_current_migration_state()


@pytest.mark.django_db(transaction=True)
def test_position_report_description_migration_backfills_only_proven_kiosk_descriptions(monkeypatch) -> None:
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(POSITION_REPORT_OLD_TARGET)
        old_apps = executor.loader.project_state(POSITION_REPORT_OLD_TARGET).apps
        Camp = old_apps.get_model("billing", "Camp")
        Participant = old_apps.get_model("billing", "Participant")
        FamilyMember = old_apps.get_model("billing", "ParticipantFamilyMember")
        OldCharge = old_apps.get_model("billing", "Charge")
        MealSignup = old_apps.get_model("billing", "MealSignup")
        AuditLog = old_apps.get_model("billing", "KioskActionAuditLog")
        db_alias = connection.alias

        camp = Camp.objects.using(db_alias).create(name="Positionsbericht Migration", year=2041)
        actor = Participant.objects.using(db_alias).create(camp=camp, first_name="Ada", last_name="Actor")
        partner = Participant.objects.using(db_alias).create(
            camp=camp,
            first_name="Peter",
            last_name="Partner",
        )
        family_member = FamilyMember.objects.using(db_alias).create(
            guardian=actor,
            first_name="Fiona",
            last_name="Familie",
            role="child",
        )
        renamed_family_member = FamilyMember.objects.using(db_alias).create(
            guardian=actor,
            first_name="Neu",
            last_name="Name",
            role="child",
        )
        conflicting_family_member = FamilyMember.objects.using(db_alias).create(
            guardian=actor,
            first_name="Konflikt",
            last_name="Familie",
            role="child",
        )
        separator_name_member = FamilyMember.objects.using(db_alias).create(
            guardian=actor,
            first_name="Anna",
            last_name="Müller",
            role="child",
        )

        family_charge = OldCharge.objects.using(db_alias).create(
            participant=actor,
            family_member=family_member,
            kiosk_booked_by=actor,
            kind="food",
            description="Abendessen für Fiona Familie",
            unit_price=Decimal("8.00"),
        )
        MealSignup.objects.using(db_alias).create(
            participant=actor,
            family_member=family_member,
            meal_date="2041-07-01",
            meal="dinner",
            variant="normal_child",
            charge=family_charge,
        )
        assert AuditLog.objects.using(db_alias).filter(charge=family_charge).exists() is False
        missing_signup_charge = OldCharge.objects.using(db_alias).create(
            participant=actor,
            family_member=family_member,
            kiosk_booked_by=actor,
            kind="food",
            description="Frühstück für Fiona Familie",
            unit_price=Decimal("6.00"),
        )
        renamed_target_charge = OldCharge.objects.using(db_alias).create(
            participant=actor,
            family_member=renamed_family_member,
            kiosk_booked_by=actor,
            kind="food",
            description="Abendessen für Alt Name",
            unit_price=Decimal("8.00"),
        )
        MealSignup.objects.using(db_alias).create(
            participant=actor,
            family_member=renamed_family_member,
            meal_date="2041-07-02",
            meal="dinner",
            variant="normal_child",
            charge=renamed_target_charge,
        )
        conflicting_signup_charge = OldCharge.objects.using(db_alias).create(
            participant=actor,
            family_member=family_member,
            kiosk_booked_by=actor,
            kind="food",
            description="Abendessen für Fiona Familie",
            unit_price=Decimal("8.00"),
        )
        MealSignup.objects.using(db_alias).create(
            participant=actor,
            family_member=conflicting_family_member,
            meal_date="2041-07-03",
            meal="dinner",
            variant="normal_child",
            charge=conflicting_signup_charge,
        )
        ambiguous_signup_charge = OldCharge.objects.using(db_alias).create(
            participant=actor,
            family_member=family_member,
            kiosk_booked_by=actor,
            kind="food",
            description="Abendessen für Fiona Familie",
            unit_price=Decimal("8.00"),
        )
        for meal_date in ("2041-07-04", "2041-07-05"):
            MealSignup.objects.using(db_alias).create(
                participant=actor,
                family_member=family_member,
                meal_date=meal_date,
                meal="dinner",
                variant="normal_child",
                charge=ambiguous_signup_charge,
            )
        separator_name_charge = OldCharge.objects.using(db_alias).create(
            participant=actor,
            family_member=separator_name_member,
            kiosk_booked_by=actor,
            kind="drink",
            description="Wasser (Kiosk) für Hans für Anna Müller",
            unit_price=Decimal("2.50"),
        )
        AuditLog.objects.using(db_alias).create(
            camp=camp,
            actor_participant=actor,
            target_participant=actor,
            target_family_member=separator_name_member,
            target_display_name_snapshot="Hans für Anna Müller",
            charge=separator_name_charge,
            action="quick_booked",
            description="Schnellbuchung erstellt.",
        )
        partner_quick_charge = OldCharge.objects.using(db_alias).create(
            participant=partner,
            kiosk_booked_by=actor,
            kind="drink",
            description="Wasser (Kiosk) für Peter Partner",
            unit_price=Decimal("2.50"),
        )
        AuditLog.objects.using(db_alias).create(
            camp=camp,
            actor_participant=actor,
            target_participant=partner,
            target_display_name_snapshot="Peter Partner",
            charge=partner_quick_charge,
            action="quick_booked",
            description="Schnellbuchung erstellt.",
        )
        partner_meal_charge = OldCharge.objects.using(db_alias).create(
            participant=partner,
            kiosk_booked_by=actor,
            kind="food",
            description="Menü für Helfer Abendessen",
            unit_price=Decimal("8.00"),
        )
        AuditLog.objects.using(db_alias).create(
            camp=camp,
            actor_participant=actor,
            target_participant=partner,
            target_display_name_snapshot="Peter Partner",
            charge=partner_meal_charge,
            action="meal_booked",
            description="Essensanmeldung gespeichert.",
        )
        manual_charge = OldCharge.objects.using(db_alias).create(
            participant=actor,
            family_member=family_member,
            kind="donation",
            description="Spende für Neu Familie",
            unit_price=Decimal("25.00"),
        )
        unproven_kiosk_charge = OldCharge.objects.using(db_alias).create(
            participant=partner,
            kiosk_booked_by=actor,
            kind="drink",
            description="Unbelegt für Peter Partner",
            unit_price=Decimal("2.50"),
        )
        ambiguous_charge = OldCharge.objects.using(db_alias).create(
            participant=partner,
            kiosk_booked_by=actor,
            kind="drink",
            description="Artikel für Alt für Name",
            unit_price=Decimal("2.50"),
        )
        for snapshot in ("Alt für Name", "Name"):
            AuditLog.objects.using(db_alias).create(
                camp=camp,
                actor_participant=actor,
                target_participant=partner,
                target_display_name_snapshot=snapshot,
                charge=ambiguous_charge,
                action="quick_booked",
                description="Schnellbuchung erstellt.",
            )

        position_report_migration = importlib.import_module(
            "billing.migrations.0068_charge_position_report_description"
        )
        monkeypatch.setattr(position_report_migration, "BATCH_SIZE", 3, raising=False)
        executor = MigrationExecutor(connection)
        with CaptureQueriesContext(connection) as migration_queries:
            executor.migrate(POSITION_REPORT_NEW_TARGET)
        new_apps = executor.loader.project_state(POSITION_REPORT_NEW_TARGET).apps
        NewCharge = new_apps.get_model("billing", "Charge")
        expected = {
            family_charge.pk: "Abendessen",
            missing_signup_charge.pk: None,
            renamed_target_charge.pk: None,
            conflicting_signup_charge.pk: None,
            ambiguous_signup_charge.pk: None,
            separator_name_charge.pk: "Wasser (Kiosk)",
            partner_quick_charge.pk: "Wasser (Kiosk)",
            partner_meal_charge.pk: "Menü für Helfer Abendessen",
            manual_charge.pk: None,
            unproven_kiosk_charge.pk: None,
            ambiguous_charge.pk: None,
        }
        assert (
            dict(
                NewCharge.objects.using(db_alias)
                .filter(pk__in=expected)
                .values_list("pk", "position_report_description")
            )
            == expected
        )
        audit_table = AuditLog._meta.db_table
        meal_signup_table = MealSignup._meta.db_table
        audit_queries = [
            query["sql"] for query in migration_queries.captured_queries if f'FROM "{audit_table}"' in query["sql"]
        ]
        meal_signup_queries = [
            query["sql"]
            for query in migration_queries.captured_queries
            if f'FROM "{meal_signup_table}"' in query["sql"]
        ]
        assert len(audit_queries) == 4
        assert len(meal_signup_queries) == 4
        assert all(" IN (" in query for query in audit_queries)
        assert all(" IN (" in query for query in meal_signup_queries)

        with connection.schema_editor() as schema_editor:
            position_report_migration.backfill_position_report_descriptions(new_apps, schema_editor)
        assert (
            dict(
                NewCharge.objects.using(db_alias)
                .filter(pk__in=expected)
                .values_list("pk", "position_report_description")
            )
            == expected
        )
    finally:
        _restore_current_migration_state()
