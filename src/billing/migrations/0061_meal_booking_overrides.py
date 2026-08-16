from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0060_shiftassignment_family_member"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="mealorder",
            name="is_sent",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="mealorder",
            name="unmarked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="mealorder",
            name="unmarked_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="unmarked_meal_orders",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="MealBookingOverride",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("meal_date", models.DateField()),
                (
                    "meal",
                    models.CharField(
                        choices=[("breakfast", "Frühstück"), ("dinner", "Abendessen")],
                        max_length=20,
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[("open", "Offen"), ("closed", "Geschlossen")],
                        max_length=10,
                    ),
                ),
                ("changed_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "camp",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="meal_booking_overrides",
                        to="billing.camp",
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="meal_booking_overrides",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["meal_date", "meal"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("camp", "meal_date", "meal"),
                        name="unique_meal_booking_override",
                    )
                ],
            },
        ),
    ]
