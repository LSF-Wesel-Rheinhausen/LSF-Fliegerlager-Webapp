from datetime import time

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0033_charge_kiosk_booked_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="settlementrun",
            name="run_type",
            field=models.CharField(
                choices=[("manual", "Manuell"), ("daily_backup", "Tägliches Backup")],
                default="manual",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="DailySettlementBackupSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("enabled", models.BooleanField(default=False)),
                ("run_time", models.TimeField(default=time(5, 0))),
            ],
            options={
                "verbose_name": "Tägliche Abrechnungs-Backup-Einstellung",
                "verbose_name_plural": "Tägliche Abrechnungs-Backup-Einstellungen",
            },
        ),
        migrations.CreateModel(
            name="DailySettlementBackupLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("run_date", models.DateField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("running", "Läuft"),
                            ("success", "Erfolgreich"),
                            ("failed", "Fehlgeschlagen"),
                            ("skipped", "Übersprungen"),
                        ],
                        default="running",
                        max_length=20,
                    ),
                ),
                ("backup_file", models.CharField(blank=True, max_length=255)),
                ("error", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(default=timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "camp",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="daily_backup_logs",
                        to="billing.camp",
                    ),
                ),
                (
                    "settlement_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="daily_backup_logs",
                        to="billing.settlementrun",
                    ),
                ),
            ],
            options={
                "ordering": ["-run_date", "-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="dailysettlementbackuplog",
            constraint=models.UniqueConstraint(
                condition=models.Q(("camp__isnull", False)),
                fields=("camp", "run_date"),
                name="unique_daily_settlement_backup_per_camp_date",
            ),
        ),
        migrations.AddConstraint(
            model_name="dailysettlementbackuplog",
            constraint=models.UniqueConstraint(
                condition=models.Q(("camp__isnull", True)),
                fields=("run_date",),
                name="unique_daily_settlement_backup_no_camp_date",
            ),
        ),
    ]
