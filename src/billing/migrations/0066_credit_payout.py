import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0065_payment_soft_delete_audit"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CreditPayout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                (
                    "method",
                    models.CharField(
                        choices=[
                            ("bank_transfer", "Überweisung"),
                            ("cash", "Bar"),
                            ("paypal", "PayPal"),
                        ],
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("idempotency_key", models.UUIDField(editable=False, unique=True)),
                ("external_reference", models.CharField(blank=True, max_length=120)),
                ("note", models.CharField(blank=True, max_length=180)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="credit_payouts_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "participant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="credit_payouts",
                        to="billing.participant",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddField(
            model_name="settlementrun",
            name="total_payouts",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="settlement",
            name="total_payouts",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
