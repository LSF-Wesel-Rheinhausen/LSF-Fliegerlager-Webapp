from django.db import migrations, models

TARGET_BOOKING_ACTIONS = {"quick_booked", "meal_booked"}
BATCH_SIZE = 500


def _full_name(person):
    return f"{person.first_name} {person.last_name}".strip()


def _matching_bases(description, target_names):
    bases = set()
    for target_name in target_names:
        suffix = f" für {target_name}"
        if target_name and description.endswith(suffix):
            base_description = description[: -len(suffix)]
            if base_description:
                bases.add(base_description)
    return bases


def backfill_position_report_descriptions(apps, schema_editor):
    """Backfill only unambiguous Kiosk-generated report labels."""
    charge_model = apps.get_model("billing", "Charge")
    audit_log_model = apps.get_model("billing", "KioskActionAuditLog")
    meal_signup_model = apps.get_model("billing", "MealSignup")
    db_alias = schema_editor.connection.alias
    last_charge_pk = 0
    while True:
        charge_ids = list(
            charge_model.objects.using(db_alias)
            .filter(
                pk__gt=last_charge_pk,
                position_report_description__isnull=True,
                kiosk_booked_by_id__isnull=False,
            )
            .order_by("pk")
            .values_list("pk", flat=True)[:BATCH_SIZE]
        )
        if not charge_ids:
            break
        last_charge_pk = charge_ids[-1]

        audits_by_charge = {}
        audit_rows = (
            audit_log_model.objects.using(db_alias)
            .filter(
                charge_id__in=charge_ids,
                action__in=TARGET_BOOKING_ACTIONS,
            )
            .order_by()
            .values_list(
                "charge_id",
                "action",
                "target_participant_id",
                "target_family_member_id",
                "target_display_name_snapshot",
            )
        )
        for audit_row in audit_rows.iterator(chunk_size=BATCH_SIZE):
            audits_by_charge.setdefault(audit_row[0], []).append(audit_row[1:])

        meal_signups_by_charge = {}
        meal_signup_rows = (
            meal_signup_model.objects.using(db_alias)
            .filter(charge_id__in=charge_ids)
            .order_by()
            .values_list(
                "charge_id",
                "participant_id",
                "family_member_id",
            )
        )
        for meal_signup_row in meal_signup_rows.iterator(chunk_size=BATCH_SIZE):
            meal_signups_by_charge.setdefault(meal_signup_row[0], []).append(meal_signup_row[1:])

        charges = (
            charge_model.objects.using(db_alias)
            .filter(pk__in=charge_ids)
            .select_related("participant", "family_member")
            .order_by("pk")
        )
        updates = []
        for charge in charges:
            has_family_target = charge.family_member_id is not None
            has_partner_target = charge.kiosk_booked_by_id != charge.participant_id
            if not has_family_target and not has_partner_target:
                continue

            matching_audits = [
                (action, target_name)
                for action, target_participant_id, target_family_member_id, target_name in audits_by_charge.get(
                    charge.pk, []
                )
                if target_participant_id == charge.participant_id and target_family_member_id == charge.family_member_id
            ]
            if not matching_audits:
                linked_meal_signups = meal_signups_by_charge.get(charge.pk, [])
                if not has_family_target or charge.kind != "food" or len(linked_meal_signups) != 1:
                    continue
                signup_participant_id, signup_family_member_id = linked_meal_signups[0]
                if signup_participant_id != charge.participant_id or signup_family_member_id != charge.family_member_id:
                    continue
                matching_bases = _matching_bases(charge.description, {_full_name(charge.family_member)})
                if len(matching_bases) != 1:
                    continue
                canonical_description = matching_bases.pop()
            else:
                audit_actions = {action for action, _target_name in matching_audits}
                target_names = {target_name for _action, target_name in matching_audits if target_name}
                if has_partner_target and not has_family_target:
                    if audit_actions == {"meal_booked"}:
                        canonical_description = charge.description
                    elif audit_actions != {"quick_booked"}:
                        continue
                    else:
                        matching_bases = _matching_bases(charge.description, target_names)
                        if not matching_bases:
                            matching_bases = _matching_bases(charge.description, {_full_name(charge.participant)})
                        if len(matching_bases) != 1:
                            continue
                        canonical_description = matching_bases.pop()
                else:
                    matching_bases = _matching_bases(charge.description, target_names)
                    if not matching_bases and has_family_target:
                        matching_bases = _matching_bases(charge.description, {_full_name(charge.family_member)})
                    if len(matching_bases) != 1:
                        continue
                    canonical_description = matching_bases.pop()

            charge.position_report_description = canonical_description
            updates.append(charge)

        if updates:
            charge_model.objects.using(db_alias).bulk_update(
                updates,
                ["position_report_description"],
                batch_size=BATCH_SIZE,
            )
        if len(charge_ids) < BATCH_SIZE:
            break


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0067_positive_credit_payout_amount"),
    ]

    operations = [
        migrations.AddField(
            model_name="charge",
            name="position_report_description",
            field=models.CharField(
                blank=True,
                editable=False,
                help_text=(
                    "Kanonische Artikelbezeichnung für den Positionsbericht bei maschinell erzeugten Buchungen."
                ),
                max_length=180,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_position_report_descriptions, migrations.RunPython.noop),
    ]
