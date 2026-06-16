import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone

from .models import (
    BookingAuditLog,
    Camp,
    Charge,
    DrinkEntry,
    Expense,
    ExpenseAllocation,
    MealOrder,
    MealSignup,
    Participant,
    PriceRule,
    Settlement,
    SettlementRun,
)
from .permissions import ADMIN_GROUP, EDITOR_GROUP, HUEBERS_GROUP

ZERO = Decimal("0.00")
MEAL_VARIANT_ORDER = [
    MealSignup.Variant.NORMAL,
    MealSignup.Variant.VEGAN,
    MealSignup.Variant.NORMAL_CHILD,
    MealSignup.Variant.VEGAN_CHILD,
]


@dataclass(frozen=True)
class MealCount:
    """Aggregate meal bookings for one day and meal type."""

    meal: str
    meal_label: str
    variant_counts: dict[str, int]
    active_total: int
    retracted_total: int


@dataclass(frozen=True)
class MealOverviewDay:
    """Represent one day in the caterer meal overview."""

    meal_date: date
    meals: list[MealCount]


@dataclass(frozen=True)
class AdminInterfaceContact:
    """Represent a kiosk-visible leadership contact."""

    name: str
    email: str
    phone: str
    phone_href: str


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


def is_meal_change_locked(camp: Camp, meal_date: date, now: datetime | None = None) -> bool:
    """Return whether kiosk meal changes are closed for the requested meal date.

    Args:
        camp: Camp whose cutoff time controls kiosk meal changes.
        meal_date: Meal date the participant wants to book or retract.
        now: Optional timezone-aware timestamp for tests.

    Returns:
        True when the meal date is in the past or tomorrow's bookings are past the camp cutoff time.
    """
    current_time = timezone.localtime(now) if now is not None else timezone.localtime()
    if meal_date <= current_time.date():
        return True
    cutoff_at = datetime.combine(
        current_time.date(),
        camp.meal_booking_cutoff_time,
        tzinfo=current_time.tzinfo,
    )
    return meal_date == current_time.date() + timedelta(days=1) and current_time >= cutoff_at


def meal_change_lock_message(camp: Camp, meal_date: date) -> str:
    """Return the user-facing message for a closed kiosk meal slot."""
    if meal_date <= timezone.localdate():
        return f"Buchungen und Rücknahmen für {meal_date:%d.%m.%Y} sind geschlossen."
    return (
        f"Buchungen und Rücknahmen für {meal_date:%d.%m.%Y} sind nach "
        f"{camp.meal_booking_cutoff_time:%H:%M} Uhr geschlossen."
    )


def camp_meal_dates(camp: Camp, include_dates: set[date] | None = None) -> list[date]:
    """Return the ordered meal dates that should appear in meal overviews."""
    if camp.starts_on and camp.ends_on and camp.starts_on <= camp.ends_on:
        day_count = (camp.ends_on - camp.starts_on).days
        return [camp.starts_on + timedelta(days=offset) for offset in range(day_count + 1)]
    if include_dates:
        return sorted(include_dates)
    return [timezone.localdate()]


def next_catering_order_date() -> date:
    """Return the date that should be ordered from the caterer today."""
    return timezone.localdate() + timedelta(days=1)


def meal_order_for_date(camp: Camp, meal_date: date) -> MealOrder | None:
    """Return the sent catering order marker for a camp day, if present."""
    return MealOrder.objects.select_related("ordered_by").filter(camp=camp, meal_date=meal_date).first()


def _phone_href(phone: str) -> str:
    """Return a sanitized telephone link target for a display phone number."""
    return re.sub(r"(?!^\+)[^0-9]", "", phone)


def _user_profile_phone(user: Any) -> str:
    """Return the profile phone number for a user when one exists."""
    try:
        return user.profile.phone
    except ObjectDoesNotExist:
        return ""


def admin_interface_contacts(user_model: Any) -> list[AdminInterfaceContact]:
    """Return active users who can be contacted for admin-interface meal issues."""
    users = list(
        user_model.objects.select_related("profile")
        .filter(is_active=True)
        .filter(
            Q(is_superuser=True) | Q(groups__name__in=[ADMIN_GROUP, EDITOR_GROUP, HUEBERS_GROUP]) | Q(is_staff=True)
        )
        .distinct()
        .order_by("last_name", "first_name", "username")
    )
    contacts = []
    for user in users:
        phone = _user_profile_phone(user)
        contacts.append(
            AdminInterfaceContact(
                name=user.get_full_name() or user.username,
                email=user.email,
                phone=phone,
                phone_href=_phone_href(phone),
            )
        )
    return contacts


def calculate_meal_overview(camp: Camp) -> list[MealOverviewDay]:
    """Aggregate dinner signups for a camp by day for catering orders."""
    signups = list(
        MealSignup.objects.select_related("participant", "family_member")
        .filter(participant__camp=camp)
        .order_by("meal_date", "meal", "variant")
    )
    dates = camp_meal_dates(camp, {signup.meal_date for signup in signups})
    meal_labels = dict(MealSignup.Meal.choices)
    variant_labels = dict(MealSignup.Variant.choices)
    days = []
    for meal_date in dates:
        meals = []
        for meal, _meal_label in [(MealSignup.Meal.DINNER, meal_labels[MealSignup.Meal.DINNER])]:
            scoped = [signup for signup in signups if signup.meal_date == meal_date and signup.meal == meal]
            variant_counts = {
                variant_labels[variant]: sum(
                    1 for signup in scoped if signup.status == MealSignup.Status.ACTIVE and signup.variant == variant
                )
                for variant in MEAL_VARIANT_ORDER
            }
            active_total = sum(variant_counts.values())
            retracted_total = sum(1 for signup in scoped if signup.status == MealSignup.Status.RETRACTED)
            meals.append(
                MealCount(
                    meal=meal,
                    meal_label=meal_labels[meal],
                    variant_counts=variant_counts,
                    active_total=active_total,
                    retracted_total=retracted_total,
                )
            )
        days.append(MealOverviewDay(meal_date=meal_date, meals=meals))
    return days


def _rule_applies(rule, participant):
    if participant.is_child and not rule.applies_to_children:
        return False
    if not participant.is_child and not rule.applies_to_adults:
        return False
    return True


def charge_audit_snapshot(charge: Charge) -> dict[str, str | None]:
    """Return the auditable business fields for a booking charge.

    Args:
        charge: The booking charge to serialize.

    Returns:
        A JSON-serializable snapshot of the charge fields that an admin may edit.
    """
    return {
        "booking_reference": charge.booking_reference,
        "kind": charge.kind,
        "description": charge.description,
        "quantity": str(money(charge.quantity)),
        "unit_price": str(money(charge.unit_price)),
        "foerdersatz": str(rate(charge.foerdersatz)),
        "occurred_on": charge.occurred_on.isoformat() if charge.occurred_on else None,
    }


def create_booking_audit_log(
    charge: Charge,
    before: dict[str, str | None],
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
    if charge.deleted_at is not None:
        return None
    after = charge_audit_snapshot(charge)
    if before == after:
        return None
    return BookingAuditLog.objects.create(
        participant=charge.participant,
        charge=charge,
        changed_by=changed_by,
        action=BookingAuditLog.Action.UPDATED,
        before=before,
        after=after,
    )


def create_booking_delete_audit_log(
    charge: Charge,
    before: dict[str, str | None],
    changed_by: Any,
) -> BookingAuditLog:
    """Persist an audit entry before a booking charge is deleted.

    Args:
        charge: The charge that will be deleted after the audit row is created.
        before: Snapshot captured before deletion.
        changed_by: User who performed the deletion.

    Returns:
        The created audit log entry. The charge relation remains intact because
        deletion is represented by soft-delete fields on the charge.
    """
    return BookingAuditLog.objects.create(
        participant=charge.participant,
        charge=charge,
        changed_by=changed_by,
        action=BookingAuditLog.Action.DELETED,
        before=before,
        after={},
    )


def restore_booking_from_audit_log(audit_log: BookingAuditLog, changed_by: Any) -> Charge:
    """Restore a deleted booking from its audit snapshot.

    Args:
        audit_log: The deletion audit row that contains the original charge fields.
        changed_by: User who requested the restoration.

    Returns:
        The restored charge.

    Raises:
        ValidationError: If the audit row is not a restorable deletion snapshot.
    """
    if audit_log.action != BookingAuditLog.Action.DELETED:
        raise ValidationError("Nur gelöschte Buchungen können wiederhergestellt werden.")
    if audit_log.charge_id is None:
        raise ValidationError("Diese Buchung kann ohne ursprüngliche Buchungs-ID nicht wiederhergestellt werden.")
    restored_charge = audit_log.charge
    if restored_charge is None:
        raise ValidationError("Diese Buchung kann ohne ursprüngliche Buchung nicht wiederhergestellt werden.")
    if restored_charge.deleted_at is None:
        raise ValidationError("Diese Buchung wurde bereits wiederhergestellt.")
    if audit_log.participant_id is None:
        raise ValidationError("Diese Buchung kann keinem Teilnehmer mehr zugeordnet werden.")

    before = charge_audit_snapshot(restored_charge)
    restored_charge.deleted_at = None
    restored_charge.deleted_by = None
    restored_charge.save(update_fields=["deleted_at", "deleted_by"])
    BookingAuditLog.objects.create(
        participant=audit_log.participant,
        charge=restored_charge,
        changed_by=changed_by,
        action=BookingAuditLog.Action.RESTORED,
        before=before,
        after=charge_audit_snapshot(restored_charge),
    )
    return restored_charge


def participant_camp_flat_duration(participant):
    nights = participant.actual_nights or participant.booked_nights or 0
    if nights > 7:
        return PriceRule.CampFlatDuration.TWO_WEEKS
    return PriceRule.CampFlatDuration.ONE_WEEK


def participant_camp_flat_role(participant):
    if participant.is_companion:
        return PriceRule.CampFlatRole.COMPANION
    return PriceRule.CampFlatRole.PARTICIPANT


def participant_subsidy_rate(participant, subsidy_rate):
    if not participant.is_youth_group:
        return ZERO
    raw_rate = subsidy_rate * participant.hilfssatz * participant.berufssatz
    return min(rate(raw_rate), Decimal("1.0000"))


def build_settlement_line(label, quantity, unit_price, source, subsidy_rate, participant):
    gross_total = money(quantity * unit_price)
    effective_subsidy_rate = participant_subsidy_rate(participant, subsidy_rate)
    subsidy_amount = money(gross_total * effective_subsidy_rate)
    total = money(gross_total - subsidy_amount)
    return SettlementLine(
        label=label,
        quantity=quantity,
        unit_price=money(unit_price),
        gross_total=gross_total,
        subsidy_rate=effective_subsidy_rate,
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
                subsidy_rate=rule.foerdersatz,
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
            subsidy_rate=charge.foerdersatz,
            participant=participant,
        )
        for charge in Charge.objects.filter(participant=participant, deleted_at__isnull=True)
    ]


def drink_charge_lines(participant):
    lines = []
    entries = (
        DrinkEntry.objects.filter(participant=participant)
        .values("drink", "unit_price", "foerdersatz")
        .annotate(quantity_sum=Sum("quantity"))
        .order_by("drink", "foerdersatz")
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
                subsidy_rate=entry["foerdersatz"],
                participant=participant,
            )
        )
    return lines


def shared_expense_charge_lines(participant):
    lines = []
    allocations = ExpenseAllocation.objects.filter(participant=participant).select_related("expense")
    for allocation in allocations:
        date_str = allocation.expense.paid_on.strftime('%d.%m.%Y') if allocation.expense.paid_on else ''
        date_part = f" ({date_str})" if date_str else ""
        lines.append(
            build_settlement_line(
                label=f"Umlage{date_part}: {allocation.expense.description}",
                quantity=Decimal("1.00"),
                unit_price=allocation.amount,
                source=f"expense_allocation:{allocation.pk}",
                subsidy_rate=ZERO,
                participant=participant,
            )
        )
    return lines


def calculate_participant_settlement(participant):
    participant = (
        Participant.objects.select_related("camp")
        .prefetch_related("charges", "payments", "expenses", "drink_entries", "expense_allocations__expense")
        .get(pk=participant.pk)
    )
    lines = (
        default_charge_lines(participant)
        + manual_charge_lines(participant)
        + drink_charge_lines(participant)
        + shared_expense_charge_lines(participant)
    )
    total_gross = money(sum((line.gross_total for line in lines), ZERO))
    total_subsidy = money(sum((line.subsidy_amount for line in lines), ZERO))
    total_due = money(sum((line.total for line in lines), ZERO))
    total_paid = money(participant.payments.aggregate(total=Sum("amount"))["total"])
    total_advanced = money(
        Expense.objects.filter(participant=participant, reimbursable=True, status=Expense.Status.APPROVED).aggregate(total=Sum("amount"))["total"]
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
    participants = Participant.objects.filter(camp=camp, archived_at__isnull=True).order_by("last_name", "first_name")
    return [calculate_participant_settlement(participant) for participant in participants]


def _settlement_snapshot_data(result: SettlementResult) -> dict[str, Any]:
    return {
        "participant": {
            "name": result.participant.full_name,
            "status": result.participant.status,
            "status_label": result.participant.get_status_display(),
        },
        "lines": [
            {
                "label": line.label,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "gross_total": str(line.gross_total),
                "subsidy_rate": str(line.subsidy_rate),
                "subsidy_amount": str(line.subsidy_amount),
                "total": str(line.total),
                "source": line.source,
            }
            for line in result.lines
        ],
    }


@transaction.atomic
def create_settlement_run(camp: Camp, calculated_by: Any) -> SettlementRun:
    locked_camp = Camp.objects.select_for_update().get(pk=camp.pk)
    latest_version = locked_camp.settlement_runs.aggregate(value=Max("version"))["value"] or 0
    results = calculate_camp_settlements(locked_camp)
    run = SettlementRun.objects.create(
        camp=locked_camp,
        version=latest_version + 1,
        calculated_by=calculated_by,
        participant_count=len(results),
        total_gross=money(sum((result.total_gross for result in results), ZERO)),
        total_subsidy=money(sum((result.total_subsidy for result in results), ZERO)),
        total_due=money(sum((result.total_due for result in results), ZERO)),
        total_paid=money(sum((result.total_paid for result in results), ZERO)),
        total_advanced=money(sum((result.total_advanced for result in results), ZERO)),
        balance=money(sum((result.balance for result in results), ZERO)),
    )
    Settlement.objects.bulk_create(
        [
            Settlement(
                run=run,
                participant=result.participant,
                calculated_by=calculated_by,
                participant_name=result.participant.full_name,
                participant_status=result.participant.status,
                total_gross=result.total_gross,
                total_subsidy=result.total_subsidy,
                total_due=result.total_due,
                total_paid=result.total_paid,
                total_advanced=result.total_advanced,
                balance=result.balance,
                data=_settlement_snapshot_data(result),
            )
            for result in results
        ]
    )
    return run


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


@transaction.atomic
def approve_shared_expense(expense: Expense, approved_by: Any, participant_ids: list[int] | None = None) -> None:
    if expense.status != Expense.Status.PENDING:
        raise ValidationError("Nur ausstehende Ausgaben können genehmigt werden.")

    expense.status = Expense.Status.APPROVED
    expense.approved_by = approved_by
    expense.approved_at = timezone.now()
    
    if expense.allocation_method in (Expense.AllocationMethod.NONE, Expense.AllocationMethod.COST_CENTER):
        expense.save(update_fields=["status", "approved_by", "approved_at", "allocation_method", "cost_center"])
        return

    participants = []
    if expense.allocation_method == Expense.AllocationMethod.ALL_ACTIVE:
        participants = list(Participant.objects.filter(camp=expense.camp, archived_at__isnull=True))
    elif expense.allocation_method == Expense.AllocationMethod.SELECTED:
        if not participant_ids:
            raise ValidationError("Es wurden keine Teilnehmer für die Umlage ausgewählt.")
        participants = list(Participant.objects.filter(id__in=participant_ids, camp=expense.camp))

    if not participants:
        raise ValidationError("Es konnten keine Teilnehmer für die Umlage ermittelt werden.")

    count = len(participants)
    base_amount_per_person = money(expense.amount / Decimal(count))
    remainder = expense.amount - (base_amount_per_person * count)

    allocations = []
    for i, p in enumerate(participants):
        amount = base_amount_per_person
        if remainder > 0:
            amount += Decimal("0.01")
            remainder -= Decimal("0.01")
        elif remainder < 0:
            amount -= Decimal("0.01")
            remainder += Decimal("0.01")
        allocations.append(ExpenseAllocation(expense=expense, participant=p, amount=amount))

    ExpenseAllocation.objects.bulk_create(allocations)
    expense.save(update_fields=["status", "approved_by", "approved_at", "allocation_method", "cost_center"])


@transaction.atomic
def reject_shared_expense(expense: Expense, rejected_by: Any, rejection_reason: str = "") -> None:
    if expense.status != Expense.Status.PENDING:
        raise ValidationError("Nur ausstehende Ausgaben können abgelehnt werden.")
    expense.status = Expense.Status.REJECTED
    expense.approved_by = rejected_by
    expense.approved_at = timezone.now()
    expense.rejection_reason = rejection_reason
    expense.save(update_fields=["status", "approved_by", "approved_at", "rejection_reason"])


def get_cost_center_evaluation(camp):
    expenses = Expense.objects.filter(
        camp=camp, 
        allocation_method=Expense.AllocationMethod.COST_CENTER, 
        status=Expense.Status.APPROVED
    ).select_related("participant")
    
    evaluation = {}
    for exp in expenses:
        cc = exp.get_cost_center_display() if exp.cost_center else "Ohne Kostenstelle"
        if cc not in evaluation:
            evaluation[cc] = {"total": Decimal("0.00"), "count": 0, "expenses": []}
        
        evaluation[cc]["total"] += exp.amount
        evaluation[cc]["count"] += 1
        evaluation[cc]["expenses"].append(exp)
        
    return evaluation

