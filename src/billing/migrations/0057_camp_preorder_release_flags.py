from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing", "0056_first_admin_bootstrap_lock")]

    operations = [
        migrations.AddField(
            model_name="camp",
            name="allow_breakfast_prebooking_before_camp",
            field=models.BooleanField(
                default=False,
                help_text="Frühstück kann vor Lagerbeginn im Kiosk vorbestellt werden.",
            ),
        ),
        migrations.AddField(
            model_name="camp",
            name="allow_dinner_prebooking_before_camp",
            field=models.BooleanField(
                default=False,
                help_text="Abendessen kann vor Lagerbeginn im Kiosk vorbestellt werden.",
            ),
        ),
    ]
