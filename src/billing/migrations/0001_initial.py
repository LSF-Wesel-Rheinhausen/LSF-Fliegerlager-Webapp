# Generated for the initial Fliegerlager billing schema.

import decimal
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Camp",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=160)),
                ("year", models.PositiveIntegerField()),
                ("starts_on", models.DateField(blank=True, null=True)),
                ("ends_on", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True)),
            ],
            options={"ordering": ["-year", "name"]},
        ),
        migrations.CreateModel(
            name="Participant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("first_name", models.CharField(max_length=120)),
                ("last_name", models.CharField(max_length=120)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=80)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("registered", "Angemeldet"),
                            ("active", "Aktiv"),
                            ("settled", "Abgerechnet"),
                            ("cancelled", "Storniert"),
                        ],
                        default="registered",
                        max_length=20,
                    ),
                ),
                ("is_child", models.BooleanField(default=False)),
                ("is_youth_group", models.BooleanField(default=False)),
                ("is_companion", models.BooleanField(default=False)),
                ("booked_nights", models.PositiveIntegerField(default=0)),
                ("actual_nights", models.PositiveIntegerField(default=0)),
                ("notes", models.TextField(blank=True)),
                ("camp", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participants", to="billing.camp")),
            ],
            options={"ordering": ["last_name", "first_name"]},
        ),
        migrations.CreateModel(
            name="PriceRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("camp_flat", "Lagerpauschale"),
                            ("night", "Übernachtung"),
                            ("meal", "Verpflegung"),
                            ("drink", "Getränk"),
                            ("other", "Sonstiges"),
                        ],
                        max_length=20,
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                (
                    "unit_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(decimal.Decimal("0"))],
                    ),
                ),
                ("applies_to_children", models.BooleanField(default=True)),
                ("applies_to_adults", models.BooleanField(default=True)),
                ("is_default", models.BooleanField(default=False)),
                ("camp", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="price_rules", to="billing.camp")),
            ],
            options={"ordering": ["kind", "name"]},
        ),
        migrations.CreateModel(
            name="Charge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("camp_flat", "Lagerpauschale"),
                            ("food", "Verpflegung"),
                            ("drink", "Getränke"),
                            ("other", "Sonstige Kosten"),
                        ],
                        max_length=20,
                    ),
                ),
                ("description", models.CharField(max_length=180)),
                ("quantity", models.DecimalField(decimal_places=2, default=decimal.Decimal("1.00"), max_digits=10)),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("occurred_on", models.DateField(blank=True, null=True)),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="charges", to="billing.participant")),
            ],
            options={"ordering": ["participant", "kind", "description"]},
        ),
        migrations.CreateModel(
            name="DrinkEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "drink",
                    models.CharField(
                        choices=[
                            ("iced_tea", "Eistee"),
                            ("softdrink", "Softdrink"),
                            ("water", "Wasser"),
                            ("beer", "Bier"),
                        ],
                        max_length=20,
                    ),
                ),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("booked_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="drink_entries", to="billing.participant")),
            ],
            options={"ordering": ["-booked_at", "participant"]},
        ),
        migrations.CreateModel(
            name="Expense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("category", models.CharField(max_length=120)),
                ("description", models.CharField(max_length=180)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("paid_on", models.DateField(blank=True, null=True)),
                ("reimbursable", models.BooleanField(default=True)),
                ("camp", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="expenses", to="billing.camp")),
                (
                    "participant",
                    models.ForeignKey(
                        blank=True,
                        help_text="Optional, wenn ein Teilnehmer den Betrag vorgestreckt hat.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="expenses",
                        to="billing.participant",
                    ),
                ),
            ],
            options={"ordering": ["category", "description"]},
        ),
        migrations.CreateModel(
            name="MealSignup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("meal_date", models.DateField()),
                (
                    "meal",
                    models.CharField(
                        choices=[("breakfast", "Frühstück"), ("lunch", "Mittagessen"), ("dinner", "Abendessen")],
                        max_length=20,
                    ),
                ),
                (
                    "variant",
                    models.CharField(
                        choices=[
                            ("normal", "Normal"),
                            ("vegan", "Vegan"),
                            ("normal_child", "Normal Kind"),
                            ("vegan_child", "Vegan Kind"),
                        ],
                        max_length=20,
                    ),
                ),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="meal_signups", to="billing.participant")),
            ],
            options={"ordering": ["meal_date", "meal", "participant"]},
        ),
        migrations.CreateModel(
            name="ParticipantPin",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("pin_hash", models.CharField(blank=True, max_length=256)),
                ("must_set_pin", models.BooleanField(default=True)),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="changed_participant_pins",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("participant", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="pin", to="billing.participant")),
            ],
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("paid_on", models.DateField()),
                ("method", models.CharField(blank=True, max_length=80)),
                ("note", models.CharField(blank=True, max_length=180)),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payments", to="billing.participant")),
            ],
            options={"ordering": ["-paid_on", "participant"]},
        ),
        migrations.CreateModel(
            name="Settlement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("total_due", models.DecimalField(decimal_places=2, max_digits=10)),
                ("total_paid", models.DecimalField(decimal_places=2, max_digits=10)),
                ("total_advanced", models.DecimalField(decimal_places=2, max_digits=10)),
                ("balance", models.DecimalField(decimal_places=2, max_digits=10)),
                ("data", models.JSONField(default=dict)),
                (
                    "calculated_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
                ),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="settlements", to="billing.participant")),
            ],
            options={"ordering": ["participant", "-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="camp",
            constraint=models.UniqueConstraint(fields=("name", "year"), name="unique_camp_name_year"),
        ),
        migrations.AddConstraint(
            model_name="participant",
            constraint=models.UniqueConstraint(fields=("camp", "first_name", "last_name"), name="unique_participant_name_per_camp"),
        ),
        migrations.AddConstraint(
            model_name="mealsignup",
            constraint=models.UniqueConstraint(fields=("participant", "meal_date", "meal"), name="unique_meal_signup"),
        ),
    ]
