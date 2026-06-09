from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0020_participant_archiving_single_active_camp"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SettlementRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("version", models.PositiveIntegerField()),
                ("participant_count", models.PositiveIntegerField(default=0)),
                ("total_gross", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=12)),
                ("total_subsidy", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=12)),
                ("total_due", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=12)),
                ("total_paid", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=12)),
                ("total_advanced", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=12)),
                ("balance", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=12)),
                (
                    "calculated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="calculated_settlement_runs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "camp",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="settlement_runs",
                        to="billing.camp",
                    ),
                ),
            ],
            options={"ordering": ["-version"]},
        ),
        migrations.AddField(
            model_name="settlement",
            name="participant_name",
            field=models.CharField(blank=True, max_length=250),
        ),
        migrations.AlterField(
            model_name="settlement",
            name="participant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="settlements",
                to="billing.participant",
            ),
        ),
        migrations.AddField(
            model_name="settlement",
            name="participant_status",
            field=models.CharField(blank=True, max_length=20),
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
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=10),
        ),
        migrations.AddField(
            model_name="settlement",
            name="total_subsidy",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=10),
        ),
        migrations.AddConstraint(
            model_name="settlementrun",
            constraint=models.UniqueConstraint(fields=("camp", "version"), name="unique_settlement_run_version"),
        ),
        migrations.AddConstraint(
            model_name="settlement",
            constraint=models.UniqueConstraint(
                condition=models.Q(("run__isnull", False)),
                fields=("run", "participant"),
                name="unique_participant_per_settlement_run",
            ),
        ),
    ]
