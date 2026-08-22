from decimal import Decimal

import django.core.validators
import django.db.models.functions.math
from django.db import migrations, models


def validate_historical_credit_payout_amounts(apps, schema_editor):
    CreditPayout = apps.get_model("billing", "CreditPayout")
    invalid_count = (
        CreditPayout.objects.using(schema_editor.connection.alias)
        .exclude(
            amount=django.db.models.functions.math.Round("amount", precision=2),
            amount__gte=Decimal("0.01"),
            amount__lte=Decimal("99999999.99"),
        )
        .count()
    )
    if invalid_count:
        row_label = "row" if invalid_count == 1 else "rows"
        raise RuntimeError(
            f"CreditPayout migration preflight failed: {invalid_count} {row_label} violate the amount contract "
            "(0.01 to 99999999.99 with at most 2 decimal places). Clean billing_creditpayout.amount "
            "manually before retrying; no rows were changed."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0066_credit_payout"),
    ]

    operations = [
        migrations.RunPython(
            validate_historical_credit_payout_amounts,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="creditpayout",
            name="amount",
            field=models.DecimalField(
                decimal_places=2,
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
            ),
        ),
        migrations.AddConstraint(
            model_name="creditpayout",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    amount=django.db.models.functions.math.Round("amount", precision=2),
                    amount__gte=Decimal("0.01"),
                    amount__lte=Decimal("99999999.99"),
                ),
                name="credit_payout_amount_valid",
            ),
        ),
    ]
