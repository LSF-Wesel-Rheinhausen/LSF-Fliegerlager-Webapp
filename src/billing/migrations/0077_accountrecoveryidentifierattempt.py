from django.db import migrations, models


def create_identifier_budget_lock(apps, schema_editor):
    """Create the singleton row that serializes bounded identifier allocation."""
    AccountRecoveryIdentifierAttempt = apps.get_model("billing", "AccountRecoveryIdentifierAttempt")
    AccountRecoveryIdentifierAttempt.objects.get_or_create(identifier_key="0" * 64)


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0076_account_recovery_delivery_binding"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountRecoveryIdentifierAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("identifier_key", models.CharField(max_length=64, unique=True)),
                ("request_timestamps", models.JSONField(default=list)),
            ],
            options={
                "ordering": ["-updated_at"],
                "indexes": [models.Index(fields=["updated_at"], name="recovery_ident_updated_idx")],
            },
        ),
        migrations.RunPython(create_identifier_budget_lock, migrations.RunPython.noop),
    ]
