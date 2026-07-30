from django.db import migrations

MUTATION_PERMISSION_CODENAMES = (
    "add_participantbookinglink",
    "change_participantbookinglink",
    "delete_participantbookinglink",
)
DEFAULT_ROLE_NAMES = ("Admin", "Bearbeiter")


def remove_booking_link_mutation_permissions(apps, _schema_editor):
    """Keep partner authorization activation exclusive to participant consent."""
    group_model = apps.get_model("auth", "Group")
    permission_model = apps.get_model("auth", "Permission")
    mutation_permissions = permission_model.objects.filter(
        content_type__app_label="billing",
        content_type__model="participantbookinglink",
        codename__in=MUTATION_PERMISSION_CODENAMES,
    )
    for group in group_model.objects.filter(name__in=DEFAULT_ROLE_NAMES):
        group.permissions.remove(*mutation_permissions)


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("billing", "0050_kiosk_audit_display_name_snapshots"),
    ]

    operations = [
        migrations.RunPython(remove_booking_link_mutation_permissions, migrations.RunPython.noop),
    ]
