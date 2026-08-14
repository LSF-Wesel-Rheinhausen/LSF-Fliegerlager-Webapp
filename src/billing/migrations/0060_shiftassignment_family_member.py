from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0059_participantfamilymember_is_youth_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="shiftassignment",
            name="family_member",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="shift_assignments",
                to="billing.participantfamilymember",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="shiftassignment",
            name="unique_shift_assignment",
        ),
        migrations.AddConstraint(
            model_name="shiftassignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("family_member__isnull", True)),
                fields=("shift", "participant"),
                name="unique_shift_assignment",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftassignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("family_member__isnull", False)),
                fields=("shift", "participant", "family_member"),
                name="unique_family_member_shift_assignment",
            ),
        ),
    ]
