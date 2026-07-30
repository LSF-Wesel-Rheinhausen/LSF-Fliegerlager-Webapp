from django.db import migrations, models


def _full_name(person):
    return f"{person.first_name} {person.last_name}".strip()


def backfill_display_name_snapshots(apps, schema_editor):
    """Freeze the best available actor and target names for existing audit rows."""
    audit_log_model = apps.get_model("billing", "KioskActionAuditLog")
    audit_logs = audit_log_model.objects.select_related(
        "actor_participant",
        "actor_family_member",
        "target_participant",
        "target_family_member",
    ).order_by("pk")
    batch = []
    for audit_log in audit_logs.iterator(chunk_size=500):
        actor = audit_log.actor_family_member or audit_log.actor_participant
        target = audit_log.target_family_member or audit_log.target_participant
        audit_log.actor_display_name_snapshot = _full_name(actor) if actor is not None else "Unbekannter Akteur"
        audit_log.target_display_name_snapshot = _full_name(target) if target is not None else "Unbekanntes Ziel"
        batch.append(audit_log)
        if len(batch) == 500:
            audit_log_model.objects.bulk_update(
                batch,
                ["actor_display_name_snapshot", "target_display_name_snapshot"],
                batch_size=500,
            )
            batch.clear()
    if batch:
        audit_log_model.objects.bulk_update(
            batch,
            ["actor_display_name_snapshot", "target_display_name_snapshot"],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0049_protect_kiosk_audit_family_members"),
    ]

    operations = [
        migrations.AddField(
            model_name="kioskactionauditlog",
            name="actor_display_name_snapshot",
            field=models.CharField(blank=True, default="", editable=False, max_length=241),
        ),
        migrations.AddField(
            model_name="kioskactionauditlog",
            name="target_display_name_snapshot",
            field=models.CharField(blank=True, default="", editable=False, max_length=241),
        ),
        migrations.RunPython(backfill_display_name_snapshots, migrations.RunPython.noop),
    ]
