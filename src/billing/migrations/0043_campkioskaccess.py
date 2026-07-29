import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0042_alter_participant_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CampKioskAccess",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("pin_hash", models.CharField(blank=True, max_length=256)),
                ("generation", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("rotated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "camp",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="kiosk_access",
                        to="billing.camp",
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="changed_camp_kiosk_access",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
