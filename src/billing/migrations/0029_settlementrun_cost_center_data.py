from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0028_expense_cost_center_alter_expense_allocation_method"),
    ]

    operations = [
        migrations.AddField(
            model_name="settlementrun",
            name="cost_center_data",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
