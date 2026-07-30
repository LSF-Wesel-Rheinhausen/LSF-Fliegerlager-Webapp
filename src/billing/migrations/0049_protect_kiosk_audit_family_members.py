import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0048_mealsignup_retraction_version"),
    ]

    operations = [
        migrations.AlterField(
            model_name="kioskactionauditlog",
            name="actor_family_member",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="performed_kiosk_action_audit_logs",
                to="billing.participantfamilymember",
            ),
        ),
        migrations.AlterField(
            model_name="kioskactionauditlog",
            name="target_family_member",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="received_kiosk_action_audit_logs",
                to="billing.participantfamilymember",
            ),
        ),
    ]
