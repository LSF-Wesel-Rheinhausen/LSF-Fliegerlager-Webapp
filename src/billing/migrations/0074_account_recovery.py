import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def remove_recovery_batches_on_reverse(apps, schema_editor):
    """Remove batches that the pre-recovery constraint cannot represent."""
    EmailBatch = apps.get_model("billing", "EmailBatch")
    EmailBatch.objects.using(schema_editor.connection.alias).filter(kind="account_recovery").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0073_camp_meal_notification_settings"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="pushmessage",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Ausstehend"),
                    ("processing", "In Verarbeitung"),
                    ("sent", "Gesendet"),
                    ("failed", "Fehlgeschlagen"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="pushmessage",
            name="processing_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="emailbatch",
            name="camp",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="email_batches",
                to="billing.camp",
            ),
        ),
        migrations.AlterField(
            model_name="emailbatch",
            name="kind",
            field=models.CharField(
                choices=[
                    ("information", "Information"),
                    ("settlement", "Rechnung"),
                    ("account_recovery", "Kontowiederherstellung"),
                ],
                max_length=20,
            ),
        ),
        migrations.RemoveConstraint(model_name="emailbatch", name="email_batch_run_matches_kind"),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=remove_recovery_batches_on_reverse,
        ),
        migrations.AddConstraint(
            model_name="emailbatch",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("camp__isnull", False), ("kind", "information"), ("settlement_run__isnull", True))
                    | models.Q(("camp__isnull", False), ("kind", "settlement"), ("settlement_run__isnull", False))
                    | models.Q(("kind", "account_recovery"), ("settlement_run__isnull", True))
                ),
                name="email_batch_run_matches_kind",
            ),
        ),
        migrations.CreateModel(
            name="AccountRecoveryToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("user_password", "Admin-Passwort"),
                            ("participant_pin", "Teilnehmer-PIN"),
                            ("family_member_pin", "Begleitpersonen-PIN"),
                        ],
                        max_length=24,
                    ),
                ),
                ("token_digest", models.CharField(blank=True, editable=False, max_length=64, null=True, unique=True)),
                ("credential_fingerprint", models.CharField(editable=False, max_length=64)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                (
                    "family_member",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="account_recovery_tokens",
                        to="billing.participantfamilymember",
                    ),
                ),
                (
                    "participant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="account_recovery_tokens",
                        to="billing.participant",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="account_recovery_tokens",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-pk"],
                "indexes": [models.Index(fields=["token_digest", "expires_at"], name="recovery_token_lookup_idx")],
                "constraints": [
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                ("family_member__isnull", True),
                                ("kind", "user_password"),
                                ("participant__isnull", True),
                                ("user__isnull", False),
                            )
                            | models.Q(
                                ("family_member__isnull", True),
                                ("kind", "participant_pin"),
                                ("participant__isnull", False),
                                ("user__isnull", True),
                            )
                            | models.Q(
                                ("family_member__isnull", False),
                                ("kind", "family_member_pin"),
                                ("participant__isnull", True),
                                ("user__isnull", True),
                            )
                        ),
                        name="recovery_token_owner_matches_kind",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="AccountRecoveryAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("client_key", models.CharField(max_length=64, unique=True)),
                ("request_timestamps", models.JSONField(default=list)),
            ],
            options={
                "ordering": ["-updated_at"],
                "indexes": [models.Index(fields=["updated_at"], name="recovery_attempt_updated_idx")],
            },
        ),
        migrations.AddField(
            model_name="emaildelivery",
            name="account_recovery",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="email_deliveries",
                to="billing.accountrecoverytoken",
            ),
        ),
        migrations.AddField(
            model_name="pushmessage",
            name="account_recovery",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="push_messages",
                to="billing.accountrecoverytoken",
            ),
        ),
    ]
