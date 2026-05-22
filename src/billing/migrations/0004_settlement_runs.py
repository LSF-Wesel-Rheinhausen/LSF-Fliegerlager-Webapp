from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("billing", "0003_repair_pricerule_camp_flat_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="SettlementRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("participant_count", models.PositiveIntegerField(default=0)),
                ("total_gross", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("total_subsidy", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("total_due", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("total_paid", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("total_advanced", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("balance", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("data", models.JSONField(blank=True, default=dict)),
                (
                    "camp",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="settlement_runs",
                        to="billing.camp",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_settlement_runs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddField(
            model_name="settlement",
            name="run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="settlements",
                to="billing.settlementrun",
            ),
        ),
        migrations.AddField(
            model_name="settlement",
            name="total_gross",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10),
        ),
        migrations.AddField(
            model_name="settlement",
            name="total_subsidy",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10),
        ),
        migrations.AlterModelOptions(
            name="settlement",
            options={"ordering": ["run", "participant", "-created_at"]},
        ),
    ]
