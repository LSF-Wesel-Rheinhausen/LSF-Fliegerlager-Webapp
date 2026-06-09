import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def normalize_active_camp(apps, schema_editor):
    Camp = apps.get_model("billing", "Camp")
    active = list(Camp.objects.filter(is_active=True).order_by("-updated_at", "-pk"))
    if active:
        Camp.objects.filter(is_active=True).exclude(pk=active[0].pk).update(is_active=False)
    else:
        camp = Camp.objects.order_by("-updated_at", "-pk").first()
        if camp is not None:
            camp.is_active = True
            camp.save(update_fields=["is_active"])


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0019_dailyshifttemplate_dailyshiftexception"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="participant",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="participant",
            name="archived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="archived_participants",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(normalize_active_camp, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="camp",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)), fields=("is_active",), name="unique_active_camp"
            ),
        ),
    ]
