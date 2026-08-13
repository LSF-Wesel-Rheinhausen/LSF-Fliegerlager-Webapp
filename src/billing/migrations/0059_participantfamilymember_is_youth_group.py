from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing", "0058_charge_family_member_attribution")]

    operations = [
        migrations.AddField(
            model_name="participantfamilymember",
            name="is_youth_group",
            field=models.BooleanField(
                default=False,
                help_text="Förderfähige Kosten werden mit Hilfssatz und Berufssatz 1,0000 berechnet.",
            ),
        ),
    ]
