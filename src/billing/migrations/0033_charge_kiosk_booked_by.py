from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0032_mealplanentry"),
    ]

    operations = [
        migrations.AddField(
            model_name="charge",
            name="kiosk_booked_by",
            field=models.ForeignKey(
                blank=True,
                help_text="Teilnehmer, der diese Kiosk-Schnellbuchung ausgelöst hat.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="kiosk_created_charges",
                to="billing.participant",
            ),
        ),
    ]
