import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0043_campkioskaccess"),
    ]

    operations = [
        migrations.CreateModel(
            name="CampKioskAccessAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("client_key", models.CharField(max_length=64)),
                ("failure_timestamps", models.JSONField(default=list)),
                (
                    "access",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attempt_states",
                        to="billing.campkioskaccess",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["updated_at"], name="kiosk_attempt_updated_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("access", "client_key"),
                        name="unique_kiosk_attempt_client",
                    ),
                ],
            },
        ),
    ]
