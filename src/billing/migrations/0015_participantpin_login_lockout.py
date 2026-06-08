from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing", "0014_subsidy_rate_per_price_element")]

    operations = [
        migrations.AddField(
            model_name="participantpin",
            name="failed_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="participantpin",
            name="locked_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
