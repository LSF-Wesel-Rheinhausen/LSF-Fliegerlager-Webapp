import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0071_alter_camp_field_verbose_names"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="shift",
            name="assignment_revision",
            field=models.PositiveBigIntegerField(default=0, editable=False),
        ),
        migrations.AlterField(
            model_name="shiftassignment",
            name="family_member",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="shift_assignments",
                to="billing.participantfamilymember",
            ),
        ),
        migrations.CreateModel(
            name="ShiftAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("added", "Eingetragen"),
                            ("removed", "Ausgetragen"),
                            ("capacity_override", "Kapazität unterschritten"),
                        ],
                        max_length=32,
                    ),
                ),
                ("identity_name_snapshot", models.CharField(blank=True, max_length=241)),
                ("shift_id_snapshot", models.PositiveBigIntegerField(editable=False)),
                ("shift_name_snapshot", models.CharField(editable=False, max_length=120)),
                ("shift_date_snapshot", models.DateField(editable=False)),
                ("before", models.JSONField(default=dict)),
                ("after", models.JSONField(default=dict)),
                ("capacity_override", models.BooleanField(default=False)),
                ("historical_override", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "camp",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="shift_audit_logs", to="billing.camp"
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="shift_audit_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "family_member",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="shift_audit_logs",
                        to="billing.participantfamilymember",
                    ),
                ),
                (
                    "participant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="shift_audit_logs",
                        to="billing.participant",
                    ),
                ),
                (
                    "shift",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_logs",
                        to="billing.shift",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["shift", "-created_at"], name="shift_audit_shift_created"),
                    models.Index(fields=["camp", "-created_at"], name="shift_audit_camp_created"),
                ],
            },
        ),
    ]
