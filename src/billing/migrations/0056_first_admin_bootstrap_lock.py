from django.db import migrations, models


def seed_first_admin_bootstrap_lock(apps, schema_editor):
    lock_model = apps.get_model("billing", "FirstAdminBootstrapLock")
    lock_model.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0055_alter_pricerule_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="FirstAdminBootstrapLock",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False),
                ),
            ],
            options={
                "verbose_name": "Sperre für Ersteinrichtung",
                "verbose_name_plural": "Sperre für Ersteinrichtung",
            },
        ),
        migrations.RunPython(seed_first_admin_bootstrap_lock, migrations.RunPython.noop),
    ]
