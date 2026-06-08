from decimal import Decimal

import django.core.validators
from django.db import migrations, models

ZERO = Decimal("0")


def migrate_subsidy_rates(apps, schema_editor):
    Camp = apps.get_model("billing", "Camp")
    PriceRule = apps.get_model("billing", "PriceRule")
    Charge = apps.get_model("billing", "Charge")
    MealSignup = apps.get_model("billing", "MealSignup")
    DrinkEntry = apps.get_model("billing", "DrinkEntry")
    BookingAuditLog = apps.get_model("billing", "BookingAuditLog")

    camp_rates = dict(Camp.objects.values_list("pk", "foerdersatz"))
    for rule in PriceRule.objects.all().iterator():
        rule.foerdersatz = camp_rates.get(rule.camp_id, ZERO) if rule.foerderfaehig else ZERO
        rule.save(update_fields=["foerdersatz"])

    for charge in Charge.objects.select_related("participant").all().iterator():
        charge.foerdersatz = camp_rates.get(charge.participant.camp_id, ZERO) if charge.foerderfaehig else ZERO
        charge.save(update_fields=["foerdersatz"])

    for signup in MealSignup.objects.select_related("participant").all().iterator():
        signup.foerdersatz = camp_rates.get(signup.participant.camp_id, ZERO) if signup.foerderfaehig else ZERO
        signup.save(update_fields=["foerdersatz"])

    for entry in DrinkEntry.objects.select_related("participant").all().iterator():
        entry.foerdersatz = camp_rates.get(entry.participant.camp_id, ZERO) if entry.foerderfaehig else ZERO
        entry.save(update_fields=["foerdersatz"])

    for audit_log in BookingAuditLog.objects.select_related("participant", "charge__participant").all().iterator():
        participant = audit_log.participant
        if participant is None and audit_log.charge is not None:
            participant = audit_log.charge.participant
        camp_rate = camp_rates.get(participant.camp_id, ZERO) if participant is not None else ZERO
        changed = False
        for snapshot_name in ("before", "after"):
            snapshot = getattr(audit_log, snapshot_name)
            if "foerderfaehig" not in snapshot:
                continue
            eligible = snapshot.pop("foerderfaehig")
            snapshot["foerdersatz"] = str(camp_rate if eligible else ZERO)
            changed = True
        if changed:
            audit_log.save(update_fields=["before", "after"])


def restore_subsidy_flags(apps, schema_editor):
    for model_name in ("PriceRule", "Charge", "MealSignup", "DrinkEntry"):
        model = apps.get_model("billing", model_name)
        for instance in model.objects.all().iterator():
            instance.foerderfaehig = instance.foerdersatz > ZERO
            instance.save(update_fields=["foerderfaehig"])

    BookingAuditLog = apps.get_model("billing", "BookingAuditLog")
    for audit_log in BookingAuditLog.objects.all().iterator():
        changed = False
        for snapshot_name in ("before", "after"):
            snapshot = getattr(audit_log, snapshot_name)
            if "foerdersatz" not in snapshot:
                continue
            snapshot["foerderfaehig"] = Decimal(snapshot.pop("foerdersatz")) > ZERO
            changed = True
        if changed:
            audit_log.save(update_fields=["before", "after"])


rate_field = models.DecimalField(
    decimal_places=4,
    default=ZERO,
    max_digits=5,
    validators=[
        django.core.validators.MinValueValidator(ZERO),
        django.core.validators.MaxValueValidator(Decimal("1")),
    ],
)


class Migration(migrations.Migration):
    dependencies = [("billing", "0013_remove_legacy_charge_cancellation_columns")]

    operations = [
        migrations.AddField(model_name="pricerule", name="foerdersatz", field=rate_field),
        migrations.AddField(model_name="charge", name="foerdersatz", field=rate_field),
        migrations.AddField(model_name="mealsignup", name="foerdersatz", field=rate_field),
        migrations.AddField(model_name="drinkentry", name="foerdersatz", field=rate_field),
        migrations.RunPython(migrate_subsidy_rates, restore_subsidy_flags),
        migrations.RemoveField(model_name="pricerule", name="foerderfaehig"),
        migrations.RemoveField(model_name="charge", name="foerderfaehig"),
        migrations.RemoveField(model_name="mealsignup", name="foerderfaehig"),
        migrations.RemoveField(model_name="drinkentry", name="foerderfaehig"),
        migrations.RemoveField(model_name="camp", name="foerdersatz"),
    ]
