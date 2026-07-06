from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0031_pricerule_is_archived"),
    ]

    operations = [
        migrations.CreateModel(
            name="MealPlanEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("meal_date", models.DateField()),
                (
                    "meal",
                    models.CharField(choices=[("breakfast", "Frühstück"), ("dinner", "Abendessen")], max_length=20),
                ),
                ("description", models.TextField(blank=True)),
                (
                    "camp",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="meal_plan_entries",
                        to="billing.camp",
                    ),
                ),
            ],
            options={
                "ordering": ["meal_date", "meal"],
            },
        ),
        migrations.AddConstraint(
            model_name="mealplanentry",
            constraint=models.UniqueConstraint(fields=("camp", "meal_date", "meal"), name="unique_meal_plan_entry"),
        ),
    ]
