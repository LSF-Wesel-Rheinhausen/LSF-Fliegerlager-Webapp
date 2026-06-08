from typing import Any

from django.db import migrations

LEGACY_CHARGE_COLUMNS = (
    "cancellation_note",
    "cancelled_at",
    "cancelled_by_id",
    "is_cancelled",
)


def _column_names(schema_editor: Any, table_name: str) -> set[str]:
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return {column.name for column in description}


def remove_legacy_charge_cancellation_columns(apps: Any, schema_editor: Any) -> None:
    Charge = apps.get_model("billing", "Charge")
    BookingAuditLog = apps.get_model("billing", "BookingAuditLog")
    charge_table = Charge._meta.db_table
    audit_table = BookingAuditLog._meta.db_table
    quote = schema_editor.quote_name
    columns = _column_names(schema_editor, charge_table)

    legacy_columns = set(LEGACY_CHARGE_COLUMNS) & columns
    if not legacy_columns:
        return

    assignments = []
    if "is_cancelled" in columns and "deleted_at" in columns:
        cancellation_time = quote("cancelled_at") if "cancelled_at" in columns else quote("updated_at")
        assignments.append(
            f"{quote('deleted_at')} = COALESCE({quote('deleted_at')}, {cancellation_time}, {quote('updated_at')})"
        )
    if "is_cancelled" in columns and "deleted_by_id" in columns and "cancelled_by_id" in columns:
        assignments.append(f"{quote('deleted_by_id')} = COALESCE({quote('deleted_by_id')}, {quote('cancelled_by_id')})")
    if "is_cancelled" in columns and assignments:
        schema_editor.execute(
            f"UPDATE {quote(charge_table)} SET {', '.join(assignments)} WHERE {quote('is_cancelled')} = %s",
            [True],
        )

    if audit_table in schema_editor.connection.introspection.table_names():
        schema_editor.execute(
            f"UPDATE {quote(audit_table)} SET {quote('action')} = %s WHERE {quote('action')} = %s",
            ["deleted", "cancelled"],
        )

    if schema_editor.connection.vendor == "sqlite" and "cancelled_by_id" in columns:
        with schema_editor.connection.cursor() as cursor:
            constraints = schema_editor.connection.introspection.get_constraints(cursor, charge_table)
        for name, details in constraints.items():
            if details.get("index") and details.get("columns") == ["cancelled_by_id"]:
                schema_editor.execute(f"DROP INDEX IF EXISTS {quote(name)}")

    for column in LEGACY_CHARGE_COLUMNS:
        if column in columns:
            schema_editor.execute(f"ALTER TABLE {quote(charge_table)} DROP COLUMN {quote(column)}")


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0012_mealorder"),
    ]

    operations = [
        migrations.RunPython(remove_legacy_charge_cancellation_columns, migrations.RunPython.noop),
    ]
