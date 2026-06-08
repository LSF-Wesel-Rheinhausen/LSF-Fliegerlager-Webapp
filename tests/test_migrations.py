import importlib
from decimal import Decimal

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from billing.models import BookingAuditLog, Charge
from tests.factories import ChargeFactory, UserFactory

migration = importlib.import_module("billing.migrations.0013_remove_legacy_charge_cancellation_columns")


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
