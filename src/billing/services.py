from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import BookingAuditLog, Charge, DrinkEntry, Expense, MealSignup, Participant, PriceRule

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class SettlementLine:
    label: str
    quantity: Decimal
    unit_price: Decimal
    gross_total: Decimal
    subsidy_rate: Decimal
    subsidy_amount: Decimal
    total: Decimal
    source: str

    @property
    def is_automatic(self) -> bool:
        return self.source.startswith("price_rule:")


@dataclass(frozen=True)
class SettlementResult:
    participant: Participant
    lines: list[SettlementLine]
    total_gross: Decimal
    total_subsidy: Decimal
    total_due: Decimal
    total_paid: Decimal
    total_advanced: Decimal
    balance: Decimal

    @property
    def automatic_lines(self) -> list["SettlementLine"]:
        return [line for line in self.lines if line.is_automatic]

    @property
    def is_overpaid(self):
        return self.balance < ZERO


def money(value):
    return (value or ZERO).quantize(Decimal("0.01"))


def rate(value):
    return (value or ZERO).quantize(Decimal("0.0001"))


def _rule_applies(rule, participant):
    if participant.is_child and not rule.applies_to_children:
        return False
    if not participant.is_child and not rule.applies_to_adults:
        return False
    return True


def charge_audit_snapshot(charge: Charge) -> dict[str, str | bool | None]:
    """Return the auditable business fields for a booking charge.

    Args:
        charge: The booking charge to serialize.

    Returns:
        A JSON-serializable snapshot of the charge fields that an admin may edit.
    """
    return {
        "kind": charge.kind,
        "description": charge.description,
        "quantity": str(money(charge.quantity)),
        "unit_price": str(money(charge.unit_price)),
        "foerderfaehig": charge.foerderfaehig,
        "occurred_on": charge.occurred_on.isoformat() if charge.occurred_on else None,
        "is_cancelled": charge.is_cancelled,
        "cancelled_at": charge.cancelled_at.isoformat() if charge.cancelled_at else None,
        "cancelled_by": str(charge.cancelled_by_id) if charge.cancelled_by_id else None,
        "cancellation_note": charge.cancellation_note,
    }


def create_booking_audit_log(
    charge: Charge,
    before: dict[str, str | bool | None],
    changed_by: Any,
) -> BookingAuditLog | None:
    """Persist an audit entry when editable booking fields changed.

    Args:
        charge: The charge after saving the edit.
        before: Snapshot captured before the edit.
        changed_by: User who performed the edit.

    Returns:
        The created audit log entry, or None if no tracked field changed.
    """
    after = charge_audit_snapshot(charge)
    if before == after:
        return None
    return BookingAuditLog.objects.create(
        charge=charge,
        changed_by=changed_by,
        action=BookingAuditLog.Action.UPDATED,
        before=before,
        after=after,
    )


def meal_charge_for_signup(signup: MealSignup) -> Charge | None:
    return (
        Charge.objects.filter(
            participant=signup.participant,
            kind=Charge.Kind.FOOD,
            occurred_on=signup.meal_date,
            description__endswith=dict(MealSignup.Meal.choices).get(signup.meal, signup.meal),
        )
        .order_by("-created_at", "-id")
        .first()
    )


def _set_charge_cancellation(charge: Charge, *, cancelled: bool, changed_by: Any, note: str = "") -> BookingAuditLog:
    before = charge_audit_snapshot(charge)
    charge.is_cancelled = cancelled
    charge.cancelled_at = timezone.now() if cancelled else None
    charge.cancelled_by = changed_by if cancelled else None
    charge.cancellation_note = note if cancelled else ""
    charge.save(update_fields=["is_cancelled", "cancelled_at", "cancelled_by", "cancellation_note", "updated_at"])
    return BookingAuditLog.objects.create(
        charge=charge,
        changed_by=changed_by,
        action=BookingAuditLog.Action.CANCELLED if cancelled else BookingAuditLog.Action.RESTORED,
        before=before,
        after=charge_audit_snapshot(charge),
    )


def cancel_meal_signup(signup: MealSignup, *, changed_by: Any, note: str) -> BookingAuditLog | None:
    note = note.strip()
    with transaction.atomic():
        signup = MealSignup.objects.select_related("participant").select_for_update().get(pk=signup.pk)
        charge = meal_charge_for_signup(signup)
        if charge is not None:
            charge = Charge.objects.select_for_update().get(pk=charge.pk)
        signup.is_cancelled = True
        signup.cancelled_at = timezone.now()
        signup.cancelled_by = changed_by
        signup.cancellation_note = note
        signup.save(update_fields=["is_cancelled", "cancelled_at", "cancelled_by", "cancellation_note", "updated_at"])
        if charge is None:
            return None
        return _set_charge_cancellation(charge, cancelled=True, changed_by=changed_by, note=note)


def restore_meal_signup(signup: MealSignup, *, changed_by: Any) -> BookingAuditLog | None:
    with transaction.atomic():
        signup = MealSignup.objects.select_related("participant").select_for_update().get(pk=signup.pk)
        charge = meal_charge_for_signup(signup)
        if charge is not None:
            charge = Charge.objects.select_for_update().get(pk=charge.pk)
        signup.is_cancelled = False
        signup.cancelled_at = None
        signup.cancelled_by = None
        signup.cancellation_note = ""
        signup.save(update_fields=["is_cancelled", "cancelled_at", "cancelled_by", "cancellation_note", "updated_at"])
        if charge is None:
            return None
        return _set_charge_cancellation(charge, cancelled=False, changed_by=changed_by)


def camp_meal_overview(camp) -> list[dict[str, Any]]:
    signups = (
        MealSignup.objects.filter(participant__camp=camp)
        .select_related("participant", "cancelled_by")
        .order_by("meal_date", "meal", "participant__last_name", "participant__first_name")
    )
    grouped: dict[tuple[Any, str], dict[str, Any]] = {}
    variant_labels = dict(MealSignup.Variant.choices)
    meal_labels = dict(MealSignup.Meal.choices)
    for signup in signups:
        key = (signup.meal_date, signup.meal)
        row = grouped.setdefault(
            key,
            {
                "meal_date": signup.meal_date,
                "meal": signup.meal,
                "meal_label": meal_labels.get(signup.meal, signup.meal),
                "active_count": 0,
                "cancelled_count": 0,
                "variant_counts": {},
                "signups": [],
            },
        )
        if signup.is_cancelled:
            row["cancelled_count"] += 1
        else:
            row["active_count"] += 1
            label = variant_labels.get(signup.variant, signup.variant)
            row["variant_counts"][label] = row["variant_counts"].get(label, 0) + 1
        row["signups"].append(signup)
    return list(grouped.values())


def participant_camp_flat_duration(participant):
    nights = participant.actual_nights or participant.booked_nights or 0
    if nights > 7:
        return PriceRule.CampFlatDuration.TWO_WEEKS
    return PriceRule.CampFlatDuration.ONE_WEEK


def participant_camp_flat_role(participant):
    if participant.is_companion:
        return PriceRule.CampFlatRole.COMPANION
    return PriceRule.CampFlatRole.PARTICIPANT


def participant_subsidy_rate(participant):
    if not participant.is_youth_group:
        return ZERO
    raw_rate = participant.camp.foerdersatz * participant.hilfssatz * participant.berufssatz
    return min(rate(raw_rate), Decimal("1.0000"))


def build_settlement_line(label, quantity, unit_price, source, eligible, participant):
    gross_total = money(quantity * unit_price)
    subsidy_rate = participant_subsidy_rate(participant) if eligible else ZERO
    subsidy_amount = money(gross_total * subsidy_rate)
    total = money(gross_total - subsidy_amount)
    return SettlementLine(
        label=label,
        quantity=quantity,
        unit_price=money(unit_price),
        gross_total=gross_total,
        subsidy_rate=subsidy_rate,
        subsidy_amount=subsidy_amount,
        total=total,
        source=source,
    )


def default_charge_lines(participant):
    default_rules = PriceRule.objects.filter(camp=participant.camp, is_default=True)
    rules = list(default_rules.filter(kind=PriceRule.Kind.NIGHT))
    camp_flat_rules = default_rules.filter(kind=PriceRule.Kind.CAMP_FLAT)
    matching_camp_flat_rules = camp_flat_rules.filter(
        camp_flat_duration=participant_camp_flat_duration(participant),
        camp_flat_role=participant_camp_flat_role(participant),
    )
    if matching_camp_flat_rules.exists():
        rules.extend(matching_camp_flat_rules)
    else:
        rules.extend(camp_flat_rules.filter(camp_flat_duration="", camp_flat_role=""))
    lines = []
    for rule in rules:
        if not _rule_applies(rule, participant):
            continue
        quantity = Decimal("1.00")
        if rule.kind == PriceRule.Kind.NIGHT:
            quantity = Decimal(participant.actual_nights or participant.booked_nights or 0)
        lines.append(
            build_settlement_line(
                label=rule.name,
                quantity=quantity,
                unit_price=rule.unit_price,
                source=f"price_rule:{rule.pk}",
                eligible=rule.foerderfaehig,
                participant=participant,
            )
        )
    return lines


def manual_charge_lines(participant):
    return [
        build_settlement_line(
            label=charge.description,
            quantity=money(charge.quantity),
            unit_price=charge.unit_price,
            source=f"charge:{charge.pk}",
            eligible=charge.foerderfaehig,
            participant=participant,
        )
        for charge in participant.charges.all()
        if not charge.is_cancelled
    ]


def drink_charge_lines(participant):
    lines = []
    entries = (
        DrinkEntry.objects.filter(participant=participant)
        .values("drink", "unit_price", "foerderfaehig")
        .annotate(quantity_sum=Sum("quantity"))
        .order_by("drink", "foerderfaehig")
    )
    for entry in entries:
        quantity = Decimal(entry["quantity_sum"] or 0)
        unit_price = money(entry["unit_price"])
        lines.append(
            build_settlement_line(
                label=f"Getränke: {dict(DrinkEntry.Drink.choices).get(entry['drink'], entry['drink'])}",
                quantity=quantity,
                unit_price=unit_price,
                source=f"drink:{entry['drink']}",
                eligible=entry["foerderfaehig"],
                participant=participant,
            )
        )
    return lines


def calculate_participant_settlement(participant):
    participant = (
        Participant.objects.select_related("camp")
        .prefetch_related("charges", "payments", "expenses", "drink_entries")
        .get(pk=participant.pk)
    )
    lines = default_charge_lines(participant) + manual_charge_lines(participant) + drink_charge_lines(participant)
    total_gross = money(sum((line.gross_total for line in lines), ZERO))
    total_subsidy = money(sum((line.subsidy_amount for line in lines), ZERO))
    total_due = money(sum((line.total for line in lines), ZERO))
    total_paid = money(participant.payments.aggregate(total=Sum("amount"))["total"])
    total_advanced = money(
        Expense.objects.filter(participant=participant, reimbursable=True).aggregate(total=Sum("amount"))["total"]
    )
    balance = money(total_due - total_paid - total_advanced)
    return SettlementResult(
        participant=participant,
        lines=lines,
        total_gross=total_gross,
        total_subsidy=total_subsidy,
        total_due=total_due,
        total_paid=total_paid,
        total_advanced=total_advanced,
        balance=balance,
    )


def calculate_camp_settlements(camp):
    participants = Participant.objects.filter(camp=camp).order_by("last_name", "first_name")
    return [calculate_participant_settlement(participant) for participant in participants]


def participant_kiosk_summary(participant):
    result = calculate_participant_settlement(participant)
    return {
        "participant": participant.full_name,
        "total_gross": result.total_gross,
        "total_subsidy": result.total_subsidy,
        "total_due": result.total_due,
        "total_paid": result.total_paid,
        "total_advanced": result.total_advanced,
        "balance": result.balance,
        "lines": [
            {
                "label": line.label,
                "quantity": line.quantity,
                "gross_total": line.gross_total,
                "subsidy_amount": line.subsidy_amount,
                "total": line.total,
            }
            for line in result.lines
        ],
    }


def default_drink_price(camp):
    rule = PriceRule.objects.filter(camp=camp, kind=PriceRule.Kind.DRINK, is_default=True).order_by("name").first()
    if rule is None:
        rule = PriceRule.objects.filter(camp=camp, kind=PriceRule.Kind.DRINK).order_by("name").first()
    return money(rule.unit_price if rule else ZERO)
