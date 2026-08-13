from django.db import migrations, models
import django.db.models.deletion


def backfill_charge_family_members(apps, schema_editor):
    """Attach a charge only when its historical family meal target is unambiguous."""
    Charge = apps.get_model("billing", "Charge")
    MealSignup = apps.get_model("billing", "MealSignup")
    targets_by_charge = {}
    for signup in (
        MealSignup.objects.filter(charge__isnull=False, family_member__isnull=False)
        .select_related("family_member")
        .order_by("charge_id", "pk")
        .iterator(chunk_size=500)
    ):
        targets_by_charge.setdefault(signup.charge_id, set()).add(signup.family_member_id)

    updates = []
    charges = Charge.objects.filter(family_member__isnull=True, pk__in=targets_by_charge).iterator(chunk_size=500)
    for charge in charges:
        targets = targets_by_charge[charge.pk]
        if len(targets) != 1:
            continue
        target_id = next(iter(targets))
        target = MealSignup.objects.filter(charge_id=charge.pk, family_member_id=target_id).select_related(
            "family_member"
        ).first()
        if target is None or target.family_member.guardian_id != charge.participant_id:
            continue
        charge.family_member_id = target_id
        updates.append(charge)
        if len(updates) == 500:
            Charge.objects.bulk_update(updates, ["family_member"], batch_size=500)
            updates.clear()
    if updates:
        Charge.objects.bulk_update(updates, ["family_member"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("billing", "0057_camp_preorder_release_flags")]

    operations = [
        migrations.AddField(
            model_name="charge",
            name="family_member",
            field=models.ForeignKey(
                blank=True,
                help_text="Optionales Familienziel innerhalb des Zahlungskontos.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="charges",
                to="billing.participantfamilymember",
            ),
        ),
        migrations.AddIndex(
            model_name="charge",
            index=models.Index(fields=["participant", "family_member", "deleted_at"], name="charge_family_active"),
        ),
        migrations.RunPython(backfill_charge_family_members, migrations.RunPython.noop),
    ]
