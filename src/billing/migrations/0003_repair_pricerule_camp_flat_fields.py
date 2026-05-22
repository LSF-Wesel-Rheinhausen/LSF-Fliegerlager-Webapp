from django.db import migrations


def add_missing_pricerule_camp_flat_fields(apps, schema_editor):
    PriceRule = apps.get_model("billing", "PriceRule")
    table_name = PriceRule._meta.db_table
    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(), table_name
        )
    }

    for field_name in ["camp_flat_duration", "camp_flat_role"]:
        if field_name not in existing_columns:
            field = PriceRule._meta.get_field(field_name)
            schema_editor.add_field(PriceRule, field)


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0002_camp_foerdersatz_charge_foerderfaehig_and_more"),
    ]

    operations = [
        migrations.RunPython(add_missing_pricerule_camp_flat_fields, migrations.RunPython.noop),
    ]
