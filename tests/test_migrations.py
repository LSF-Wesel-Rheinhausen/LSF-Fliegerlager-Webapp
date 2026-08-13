import importlib
from decimal import Decimal

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from billing.models import BookingAuditLog, Charge, ParticipantBookingLink
from tests.factories import ChargeFactory, ParticipantFactory, UserFactory

migration = importlib.import_module("billing.migrations.0013_remove_legacy_charge_cancellation_columns")
partner_authorization_migration = importlib.import_module("billing.migrations.0046_kiosk_action_audit_log")
booking_link_permissions_migration = importlib.import_module(
    "billing.migrations.0051_remove_booking_link_mutation_permissions"
)


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
