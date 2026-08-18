import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import Any, TypedDict, cast

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Max, Prefetch, Q, Sum
from django.utils import timezone

from .models import (
    BookingAuditLog,
    Camp,
    Charge,
    DrinkEntry,
    Expense,
    ExpenseAllocation,
    KioskActionAuditLog,
    MealBookingOverride,
    MealOrder,
    MealPlanEntry,
    MealSignup,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    Payment,
    PaymentAuditLog,
    PriceRule,
    Settlement,
    SettlementRun,
)
from .permissions import ADMIN_GROUP, EDITOR_GROUP, HUEBERS_GROUP

ZERO = Decimal("0.00")


class ExpenseReceiptStorageError(RuntimeError):
    """Report a receipt storage failure without exposing backend details to users."""


def save_expense(expense: Expense) -> None:
    """Save an expense and normalize failures while persisting a new receipt.

    Raises:
        ExpenseReceiptStorageError: If the attached, uncommitted receipt cannot
            be written to the configured storage.
        OSError: If an unrelated storage-level error occurs.
    """
    try:
        expense.save()
    except OSError as error:
        receipt = expense.receipt
        if receipt and not getattr(receipt, "_committed", True):
            raise ExpenseReceiptStorageError from error
        raise


MEAL_VARIANT_ORDER = [
    MealSignup.Variant.NORMAL,
    MealSignup.Variant.VEGAN,
    MealSignup.Variant.NORMAL_CHILD,
    MealSignup.Variant.VEGAN_CHILD,
]
MANUAL_CHARGE_KIND_BY_PRICE_RULE_KIND = {
    PriceRule.Kind.CAMP_FLAT: Charge.Kind.CAMP_FLAT,
    PriceRule.Kind.NIGHT: Charge.Kind.OTHER,
    PriceRule.Kind.MEAL: Charge.Kind.FOOD,
    PriceRule.Kind.DRINK: Charge.Kind.DRINK,
    PriceRule.Kind.OTHER: Charge.Kind.OTHER,
}


@dataclass(frozen=True)
class MealBookingDetail:
    """Describe one meal booking for the administrator detail dialog."""

    target_name: str
    payment_account_name: str
    variant_label: str
    status_label: str


@dataclass(frozen=True)
class MealCount:
    """Aggregate meal bookings for one day and meal type."""

    meal: str
    meal_label: str
    variant_counts: dict[str, int]
    active_total: int
    retracted_total: int
    bookings: list[MealBookingDetail] = field(default_factory=list)

    @property
    def booking_total(self) -> int:
        """Return the total number of active and retracted booking records."""
        return len(self.bookings)


@dataclass(frozen=True)
class MealOverviewDay:
    """Represent one day in the caterer meal overview."""

    meal_date: date
    meals: list[MealCount]
    menu_description: str = ""
    breakfast_meals: list[MealCount] = field(default_factory=list)

    @property
    def dinner(self) -> MealCount:
        """Return the caterer dinner row for this camp day."""
        return self.meals[0]

    @property
    def breakfast(self) -> MealCount:
        """Return the breakfast preorder row for this camp day."""
        return self.breakfast_meals[0]


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
    occurred_on: date | None = None
    booking_references: tuple[str, ...] = ()
    target_name: str = ""

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

    @property
    def family_target_names(self) -> tuple[str, ...]:
        """Return stable, de-duplicated target names represented in this guardian settlement."""
        return tuple(dict.fromkeys(line.target_name for line in self.lines if line.target_name))


def money(value):
    return (value or ZERO).quantize(Decimal("0.01"))


def rate(value):
    return (value or ZERO).quantize(Decimal("0.0001"))


@transaction.atomic
def create_manual_charge(
    participant: Participant,
    price_rule: PriceRule,
    quantity: int,
    description: str,
) -> Charge:
    """Create a manual charge from validated price-rule input.

    Args:
        participant: Active participant who receives the charge.
        price_rule: Active rule from the participant's camp.
        quantity: Validated whole-number quantity between 1 and 99.
        description: Optional operator-provided description.

    Returns:
        The persisted charge containing a snapshot of the selected rule.

    Raises:
        ValidationError: If the participant or price rule is not eligible.
    """
    locked_participant = Participant.objects.select_for_update().filter(pk=participant.pk).first()
    if locked_participant is None:
        raise ValidationError(
            "Der Teilnehmer ist nicht mehr verfügbar.",
            code="manual_charge_participant_unavailable",
        )

    locked_price_rule = PriceRule.objects.select_for_update().filter(pk=price_rule.pk).first()
    if locked_price_rule is None:
        raise ValidationError("Die ausgewählte Preisregel ist nicht mehr verfügbar.")

    if locked_participant.archived_at is not None:
        raise ValidationError(
            "Für archivierte Teilnehmer können keine Buchungen erfasst werden.",
            code="manual_charge_participant_archived",
        )
    if locked_price_rule.camp_id != locked_participant.camp_id or locked_price_rule.is_archived:
        raise ValidationError("Die ausgewählte Preisregel ist für diesen Teilnehmer nicht verfügbar.")
    try:
        price_rule_kind = PriceRule.Kind(locked_price_rule.kind)
    except ValueError as error:
        raise ValidationError("Die ausgewählte Preisregel hat eine ungültige Art.") from error

    return Charge.objects.create(
        participant=locked_participant,
        kind=MANUAL_CHARGE_KIND_BY_PRICE_RULE_KIND[price_rule_kind],
        description=description.strip() or locked_price_rule.name,
        quantity=Decimal(quantity),
        unit_price=locked_price_rule.unit_price,
        foerdersatz=locked_price_rule.foerdersatz,
    )


def is_meal_change_locked(
    camp: Camp,
    meal_date: date,
    meal: str = MealSignup.Meal.DINNER,
    now: datetime | None = None,
    sent_order_dates: set[date] | None = None,
) -> bool:
    """Return whether policy closes kiosk changes for one meal date.

    Args:
        camp: Camp whose dinner-day state controls kiosk meal changes.
        meal_date: Meal date the participant wants to book or retract.
        meal: Breakfast or dinner.
        now: Optional timezone-aware timestamp for tests.
        sent_order_dates: Optional preloaded dates with a sent catering order.

    Returns:
        True for past dates, sent dinner orders, or manually closed dinners.
    """
    return bool(
        meal_booking_state(
            camp,
            meal_date,
            meal=meal,
            now=now,
            sent_order_dates=sent_order_dates,
        )["locked"]
    )


def meal_booking_state(
    camp: Camp,
    meal_date: date,
    *,
    meal: str = MealSignup.Meal.DINNER,
    now: datetime | None = None,
    override_states: Mapping[tuple[date, str], str] | None = None,
    sent_order_dates: set[date] | None = None,
) -> dict[str, str | bool]:
    """Return the effective booking state for one meal slot.

    Breakfast is open for today and future dates. A sent catering order closes
    dinner booking before manual overrides are considered; marking that order
    as not sent restores the stored manual state. The camp's reminder time is
    informational. Callers resolving several days can pass both preloaded
    collections to avoid per-day database queries.

    Args:
        camp: Camp whose dinner booking state is resolved.
        meal_date: Calendar date of the meal slot.
        meal: Breakfast or dinner.
        now: Optional timezone-aware timestamp for deterministic callers.
        override_states: Optional preloaded override states keyed by date and meal.
        sent_order_dates: Optional preloaded dates with a sent catering order.

    Returns:
        A state identifier, lock flag, and user-facing explanation.
    """
    current_time = timezone.localtime(now) if now is not None else timezone.localtime()
    today = current_time.date() if now is not None else timezone.localdate()
    if meal_date < today:
        return {
            "state": "past",
            "locked": True,
            "message": f"Buchungen und Rücknahmen für {meal_date:%d.%m.%Y} sind geschlossen.",
        }
    if meal != MealSignup.Meal.DINNER:
        return {"state": "open", "locked": False, "message": ""}
    order_was_sent = (
        meal_date in sent_order_dates
        if sent_order_dates is not None
        else MealOrder.objects.filter(camp=camp, meal_date=meal_date, is_sent=True).exists()
    )
    if order_was_sent:
        return {
            "state": "order_sent",
            "locked": True,
            "message": f"Die Bestellung für {meal_date:%d.%m.%Y} wurde bereits abgeschickt.",
        }
    override_state = (
        override_states.get((meal_date, meal))
        if override_states is not None
        else MealBookingOverride.objects.filter(camp=camp, meal_date=meal_date, meal=meal)
        .values_list("state", flat=True)
        .first()
    )
    if override_state is not None:
        if override_state == MealBookingOverride.State.OPEN:
            return {"state": "manual_open", "locked": False, "message": "Manuell wieder geöffnet."}
        return {
            "state": "manual_closed",
            "locked": True,
            "message": f"Buchungen und Rücknahmen für {meal_date:%d.%m.%Y} wurden manuell geschlossen.",
        }
    return {"state": "open", "locked": False, "message": ""}


def preload_meal_booking_state_inputs(
    camp: Camp,
    meal_dates: Iterable[date],
    *,
    meal: str,
) -> tuple[dict[tuple[date, str], str], set[date]]:
    """Load all persisted state inputs needed to resolve several meal dates.

    Args:
        camp: Camp whose persisted meal state is loaded.
        meal_dates: Dates that will be resolved in one batch.
        meal: Breakfast or dinner; breakfast returns empty collections.

    Returns:
        Override states keyed by date and meal plus dates with sent orders.
    """
    dates = set(meal_dates)
    if meal != MealSignup.Meal.DINNER or not dates:
        return {}, set()
    override_states = {
        (meal_date, stored_meal): state
        for meal_date, stored_meal, state in MealBookingOverride.objects.filter(
            camp=camp,
            meal_date__in=dates,
            meal=meal,
        ).values_list("meal_date", "meal", "state")
    }
    sent_order_dates = set(
        MealOrder.objects.filter(camp=camp, meal_date__in=dates, is_sent=True).values_list("meal_date", flat=True)
    )
    return override_states, sent_order_dates


def meal_change_lock_message(
    camp: Camp,
    meal_date: date,
    meal: str = MealSignup.Meal.DINNER,
    sent_order_dates: set[date] | None = None,
) -> str:
    """Return the user-facing message for a closed kiosk meal slot."""
    return str(
        meal_booking_state(
            camp,
            meal_date,
            meal=meal,
            sent_order_dates=sent_order_dates,
        )["message"]
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
    """Aggregate separate dinner and breakfast signups for a camp by day."""
    signup_queryset = MealSignup.objects.select_related("participant", "family_member", "family_member__guardian")
    if camp.starts_on and camp.ends_on and camp.starts_on <= camp.ends_on:
        dates = camp_meal_dates(camp)
        signups = list(
            signup_queryset.filter(
                participant__camp=camp,
                meal_date__range=(dates[0], dates[-1]),
            ).order_by("meal_date", "meal", "variant")
        )
    else:
        signups = list(signup_queryset.filter(participant__camp=camp).order_by("meal_date", "meal", "variant"))
        dates = camp_meal_dates(camp, {signup.meal_date for signup in signups})
    date_set = set(dates)
    signups = [signup for signup in signups if signup.meal_date in date_set]
    menu_descriptions = {
        entry.meal_date: entry.description
        for entry in MealPlanEntry.objects.filter(camp=camp, meal=MealSignup.Meal.DINNER)
    }
    meal_labels = dict(MealSignup.Meal.choices)
    variant_labels = dict(MealSignup.Variant.choices)

    def count_meal(meal_date: date, meal: str) -> MealCount:
        scoped = [signup for signup in signups if signup.meal_date == meal_date and signup.meal == meal]
        bookings = [
            MealBookingDetail(
                target_name=signup.family_member.full_name if signup.family_member else signup.participant.full_name,
                payment_account_name=signup.participant.full_name,
                variant_label=variant_labels[signup.variant],
                status_label=dict(MealSignup.Status.choices)[signup.status],
            )
            for signup in sorted(
                scoped,
                key=lambda signup: (
                    signup.family_member.last_name if signup.family_member else signup.participant.last_name,
                    signup.family_member.first_name if signup.family_member else signup.participant.first_name,
                    signup.participant.last_name,
                    signup.participant.first_name,
                    signup.participant_id,
                    signup.pk,
                ),
            )
        ]
        variant_counts = {
            variant_labels[variant]: sum(
                1 for signup in scoped if signup.status == MealSignup.Status.ACTIVE and signup.variant == variant
            )
            for variant in MEAL_VARIANT_ORDER
        }
        return MealCount(
            meal=meal,
            meal_label=meal_labels[meal],
            variant_counts=variant_counts,
            active_total=sum(variant_counts.values()),
            retracted_total=sum(1 for signup in scoped if signup.status == MealSignup.Status.RETRACTED),
            bookings=bookings,
        )

    days = []
    for meal_date in dates:
        dinner = count_meal(meal_date, MealSignup.Meal.DINNER)
        breakfast = count_meal(meal_date, MealSignup.Meal.BREAKFAST)
        days.append(
            MealOverviewDay(
                meal_date=meal_date,
                meals=[dinner],
                menu_description=menu_descriptions.get(meal_date, ""),
                breakfast_meals=[breakfast],
            )
        )
    return days


def _rule_applies(rule, participant):
    if participant.is_child:
        return rule.applies_to_children
    if participant.is_companion:
        return rule.applies_to_companions
    return rule.applies_to_adults


def resolve_meal_price_rule(camp: Camp, meal: str, meal_date: date, *, is_child: bool, is_companion: bool = False):
    """Return the applicable meal price rule for one person and date.

    Args:
        camp: Camp whose price rules are searched.
        meal: Meal type, for example ``MealSignup.Meal.DINNER``.
        meal_date: Date of the concrete meal booking.
        is_child: Whether child meal pricing applies.
        is_companion: Whether companion meal pricing applies.

    Returns:
        A date-specific rule for ``meal_date`` when one exists, otherwise the
        default rule with ``meal_date IS NULL``. Archived rules are ignored.
    """
    rules = PriceRule.objects.filter(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=meal,
        is_archived=False,
    ).order_by("name", "pk")
    return _resolve_meal_price_rule_from_rules(
        rules,
        meal,
        meal_date,
        is_child=is_child,
        is_companion=is_companion,
    )


def _resolve_meal_price_rule_from_rules(
    rules: Iterable[PriceRule],
    meal: str,
    meal_date: date,
    *,
    is_child: bool,
    is_companion: bool,
) -> PriceRule | None:
    """Resolve the canonical meal rule from an already loaded rule collection."""
    matching_rules = [
        rule
        for rule in rules
        if not rule.is_archived
        and rule.meal_type == meal
        and (
            rule.applies_to_children
            if is_child
            else rule.applies_to_companions
            if is_companion
            else rule.applies_to_adults
        )
    ]
    matching_rules.sort(key=lambda rule: (rule.name, rule.pk))
    date_rule = next((rule for rule in matching_rules if rule.meal_date == meal_date), None)
    if date_rule is not None:
        return date_rule
    return next(
        (rule for rule in matching_rules if rule.is_default and rule.meal_date is None),
        None,
    )


def resolve_quick_booking_price_rule(
    selected_rule: PriceRule,
    booking_date: date,
    *,
    is_child: bool,
    is_companion: bool,
) -> PriceRule | None:
    """Resolve an actor-selected quick-booking rule for one concrete target.

    Drink rules must explicitly apply to the target. Quick-food selections keep
    an applicable submitted rule, prefer a date-specific override, and resolve
    another target-group default when the submitted rule does not apply.
    """
    if is_child:
        selected_rule_applies = selected_rule.applies_to_children
    elif is_companion:
        selected_rule_applies = selected_rule.applies_to_companions
    else:
        selected_rule_applies = selected_rule.applies_to_adults
    if selected_rule.kind == PriceRule.Kind.DRINK:
        return selected_rule if selected_rule_applies else None
    if selected_rule.kind == PriceRule.Kind.MEAL:
        resolved_rule = resolve_meal_price_rule(
            selected_rule.camp,
            selected_rule.meal_type,
            booking_date,
            is_child=is_child,
            is_companion=is_companion,
        )
        if resolved_rule is not None and resolved_rule.meal_date == booking_date:
            return resolved_rule
        if selected_rule_applies:
            return selected_rule
        return resolved_rule
    return None


def charge_audit_snapshot(charge: Charge) -> dict[str, str | None]:
    """Return the auditable business fields for a booking charge.

    Args:
        charge: The booking charge to serialize.

    Returns:
        A JSON-serializable snapshot of the charge fields that an admin may edit.
    """
    snapshot = {
        "booking_reference": charge.booking_reference,
        "kind": charge.kind,
        "description": charge.description,
        "quantity": str(money(Decimal(str(charge.quantity)))),
        "unit_price": str(money(Decimal(str(charge.unit_price)))),
        "foerdersatz": str(rate(Decimal(str(charge.foerdersatz)))),
        "occurred_on": charge.occurred_on.isoformat() if charge.occurred_on else None,
    }
    family_member = charge.family_member
    if family_member is not None:
        snapshot["family_member"] = family_member.full_name
    return snapshot


def kiosk_charge_audit_snapshot(charge: Charge) -> dict[str, str | None]:
    """Return the booking fields needed to resolve participant kiosk disputes."""
    snapshot = charge_audit_snapshot(charge)
    snapshot.pop("description", None)
    snapshot.pop("family_member", None)
    snapshot["deleted_at"] = charge.deleted_at.isoformat() if charge.deleted_at else None
    return snapshot


def kiosk_meal_signup_audit_snapshot(signup: MealSignup) -> dict[str, Any]:
    """Return the meal and linked charge state relevant to kiosk disputes."""
    return {
        "meal_date": signup.meal_date.isoformat(),
        "meal": signup.meal,
        "variant": signup.variant,
        "status": signup.status,
        "retracted_at": signup.retracted_at.isoformat() if signup.retracted_at else None,
        "charge": kiosk_charge_audit_snapshot(signup.charge) if signup.charge is not None else None,
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


def create_kiosk_action_audit_log(
    *,
    camp: Camp,
    actor_participant: Participant,
    target_participant: Participant,
    action: str,
    description: str,
    actor_family_member: ParticipantFamilyMember | None = None,
    target_family_member: ParticipantFamilyMember | None = None,
    booking_link: ParticipantBookingLink | None = None,
    charge: Charge | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> KioskActionAuditLog:
    """Append one validated audit row for a current-camp kiosk action.

    Args:
        camp: Camp whose participant records are affected.
        actor_participant: Main account under which the kiosk actor is logged in.
        target_participant: Other main account involved in the action.
        action: One value from :class:`KioskActionAuditLog.Action`.
        description: Short participant-facing explanation without secrets.
        actor_family_member: Companion who actually used the actor account, if any.
        target_family_member: Family member affected below the target account, if any.
        booking_link: Partner authorization used for the action, if applicable.
        charge: Charge affected by a booking action, if applicable.
        before: JSON-serializable state before the action.
        after: JSON-serializable state after the action.

    Returns:
        The newly created append-only audit row.

    Raises:
        ValidationError: If an identity disappeared or does not belong to the supplied camp/account.
    """
    participant_ids = {actor_participant.pk, target_participant.pk}
    participants_by_id = Participant.objects.in_bulk(participant_ids)
    if set(participants_by_id) != participant_ids:
        raise ValidationError("Eine Kiosk-Audit-Identität ist nicht mehr verfügbar.")
    actor_participant = participants_by_id[actor_participant.pk]
    target_participant = participants_by_id[target_participant.pk]

    family_member_ids = {
        family_member.pk for family_member in (actor_family_member, target_family_member) if family_member is not None
    }
    family_members_by_id = ParticipantFamilyMember.objects.in_bulk(family_member_ids)
    if set(family_members_by_id) != family_member_ids:
        raise ValidationError("Eine Kiosk-Audit-Identität ist nicht mehr verfügbar.")
    actor_family_member = family_members_by_id[actor_family_member.pk] if actor_family_member is not None else None
    target_family_member = family_members_by_id[target_family_member.pk] if target_family_member is not None else None

    if actor_participant.camp_id != camp.pk or target_participant.camp_id != camp.pk:
        raise ValidationError("Kiosk-Audit darf nur Teilnehmer desselben Lagers verknüpfen.")
    if actor_family_member is not None and actor_family_member.guardian_id != actor_participant.pk:
        raise ValidationError("Die handelnde Begleitperson gehört nicht zum Akteur.")
    if target_family_member is not None and target_family_member.guardian_id != target_participant.pk:
        raise ValidationError("Das betroffene Familienmitglied gehört nicht zum Zielkonto.")
    return KioskActionAuditLog.objects.create(
        camp=camp,
        actor_participant=actor_participant,
        actor_family_member=actor_family_member,
        target_participant=target_participant,
        target_family_member=target_family_member,
        booking_link=booking_link,
        charge=charge,
        action=action,
        description=description,
        before=before or {},
        after=after or {},
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


def payment_audit_snapshot(payment: Payment) -> dict[str, str | None]:
    """Return the auditable business fields for a recorded payment.

    Args:
        payment: The payment to serialize.

    Returns:
        A JSON-serializable snapshot of the payment fields an admin may review.
    """
    return {
        "payment_reference": payment.payment_reference,
        "amount": str(money(Decimal(str(payment.amount)))),
        "paid_on": payment.paid_on.isoformat() if payment.paid_on else None,
        "method": payment.method,
        "note": payment.note,
    }


def create_payment_delete_audit_log(
    payment: Payment,
    before: dict[str, str | None],
    changed_by: Any,
) -> PaymentAuditLog:
    """Persist an audit entry before a recorded payment is soft-deleted.

    Args:
        payment: The payment that will be marked deleted after the audit row exists.
        before: Snapshot captured before deletion.
        changed_by: User who performed the deletion.

    Returns:
        The created audit log entry. The payment relation stays intact because
        deletion is represented by soft-delete fields on the payment.
    """
    return PaymentAuditLog.objects.create(
        participant=payment.participant,
        payment=payment,
        changed_by=changed_by,
        action=PaymentAuditLog.Action.DELETED,
        before=before,
        after={},
    )


def restore_payment_from_audit_log(audit_log: PaymentAuditLog, changed_by: Any) -> Payment:
    """Restore a soft-deleted payment referenced by its deletion audit entry.

    Args:
        audit_log: The deletion audit row that points at the deleted payment.
        changed_by: User who requested the restoration.

    Returns:
        The restored payment.

    Raises:
        ValidationError: If the audit row is not a restorable deletion snapshot.
    """
    if audit_log.action != PaymentAuditLog.Action.DELETED:
        raise ValidationError("Nur gelöschte Zahlungen können wiederhergestellt werden.")
    restored_payment = audit_log.payment
    if audit_log.payment_id is None or restored_payment is None:
        raise ValidationError("Diese Zahlung kann ohne ursprüngliche Zahlung nicht wiederhergestellt werden.")
    if restored_payment.deleted_at is None:
        raise ValidationError("Diese Zahlung wurde bereits wiederhergestellt.")
    if audit_log.participant_id is None:
        raise ValidationError("Diese Zahlung kann keinem Teilnehmer mehr zugeordnet werden.")

    before = payment_audit_snapshot(restored_payment)
    restored_payment.deleted_at = None
    restored_payment.deleted_by = None
    restored_payment.save(update_fields=["deleted_at", "deleted_by"])
    PaymentAuditLog.objects.create(
        participant=audit_log.participant,
        payment=restored_payment,
        changed_by=changed_by,
        action=PaymentAuditLog.Action.RESTORED,
        before=before,
        after=payment_audit_snapshot(restored_payment),
    )
    return restored_payment


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


def family_member_subsidy_rate(
    guardian: Participant,
    family_member: ParticipantFamilyMember | None,
    subsidy_rate,
) -> Decimal:
    """Calculate a family target's subsidy using its youth-group flag or guardian fallback."""
    if family_member is not None and family_member.is_youth_group:
        return min(rate(subsidy_rate), Decimal("1.0000"))
    return participant_subsidy_rate(guardian, subsidy_rate)


def build_settlement_line(
    label,
    quantity,
    unit_price,
    source,
    subsidy_rate,
    participant,
    *,
    occurred_on=None,
    booking_references=(),
    target_name: str = "",
    family_member: ParticipantFamilyMember | None = None,
):
    gross_total = money(quantity * unit_price)
    effective_subsidy_rate = family_member_subsidy_rate(participant, family_member, subsidy_rate)
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
        occurred_on=occurred_on,
        booking_references=tuple(booking_references),
        target_name=target_name,
    )


def default_charge_lines(
    participant: Participant,
    default_rules: Iterable[PriceRule] | None = None,
) -> list[SettlementLine]:
    if default_rules is None:
        default_rules = PriceRule.objects.filter(camp=participant.camp, is_default=True)
    available_rules = list(default_rules)
    rules = [rule for rule in available_rules if rule.kind == PriceRule.Kind.NIGHT]
    camp_flat_rules = [rule for rule in available_rules if rule.kind == PriceRule.Kind.CAMP_FLAT]
    matching_camp_flat_rules = [
        rule
        for rule in camp_flat_rules
        if rule.camp_flat_duration == participant_camp_flat_duration(participant)
        and rule.camp_flat_role == participant_camp_flat_role(participant)
    ]
    if matching_camp_flat_rules:
        rules.extend(matching_camp_flat_rules)
    else:
        rules.extend(rule for rule in camp_flat_rules if rule.camp_flat_duration == "" and rule.camp_flat_role == "")
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


def family_member_camp_flat_duration(member: ParticipantFamilyMember, guardian: Participant) -> str:
    """Resolve a family member's camp-fee duration from their stay, falling back to the guardian."""
    if member.arrival_date and member.departure_date and member.departure_date > member.arrival_date:
        nights = (member.departure_date - member.arrival_date).days
    else:
        nights = guardian.actual_nights or guardian.booked_nights or 0
    return PriceRule.CampFlatDuration.TWO_WEEKS if nights > 7 else PriceRule.CampFlatDuration.ONE_WEEK


def family_member_camp_flat_role(member: ParticipantFamilyMember) -> str:
    """Map a child to the participant rate and a companion to the companion rate."""
    if member.role == ParticipantFamilyMember.Role.COMPANION:
        return PriceRule.CampFlatRole.COMPANION
    return PriceRule.CampFlatRole.PARTICIPANT


def _family_member_rule_applies(rule: PriceRule, member: ParticipantFamilyMember) -> bool:
    if member.role == ParticipantFamilyMember.Role.CHILD:
        return rule.applies_to_children
    return rule.applies_to_companions


def family_camp_flat_lines(
    guardian: Participant,
    family_members: Iterable[ParticipantFamilyMember],
    default_rules: Iterable[PriceRule],
) -> list[SettlementLine]:
    """Create guardian-billed camp-fee lines for active adult companions.

    Family children are not charged a camp flat fee. Their ``role`` is the
    authoritative classification because family members do not carry age data.
    """
    camp_flat_rules = [rule for rule in default_rules if rule.kind == PriceRule.Kind.CAMP_FLAT]
    lines = []
    for member in family_members:
        if not member.is_active or member.role == ParticipantFamilyMember.Role.CHILD:
            continue
        matching_rules = [
            rule
            for rule in camp_flat_rules
            if rule.camp_flat_duration == family_member_camp_flat_duration(member, guardian)
            and rule.camp_flat_role == family_member_camp_flat_role(member)
        ]
        if not matching_rules:
            matching_rules = [
                rule for rule in camp_flat_rules if rule.camp_flat_duration == "" and rule.camp_flat_role == ""
            ]
        for rule in matching_rules:
            if not _family_member_rule_applies(rule, member):
                continue
            lines.append(
                build_settlement_line(
                    label=rule.name,
                    quantity=Decimal("1.00"),
                    unit_price=rule.unit_price,
                    source=f"price_rule:family:{rule.pk}:{member.pk}",
                    subsidy_rate=rule.foerdersatz,
                    participant=guardian,
                    target_name=member.full_name,
                    family_member=member,
                )
            )
    return lines


def manual_charge_lines(
    participant: Participant,
    charges: Iterable[Charge] | None = None,
) -> list[SettlementLine]:
    grouped_charges: dict[tuple[Any, ...], dict[str, Any]] = {}
    if charges is None:
        charges = (
            Charge.objects.filter(participant=participant, deleted_at__isnull=True)
            .select_related("family_member")
            .order_by("created_at", "pk")
        )
    for charge in charges:
        occurred_on = charge.occurred_on or timezone.localdate(charge.created_at)
        individual_line = build_settlement_line(
            label=charge.description,
            quantity=money(charge.quantity),
            unit_price=charge.unit_price,
            source=f"charge:{charge.pk}",
            subsidy_rate=charge.foerdersatz,
            participant=participant,
            family_member=charge.family_member,
        )
        key = (
            occurred_on,
            charge.kind,
            charge.description,
            charge.unit_price,
            charge.foerdersatz,
            charge.family_member_id,
        )
        group = grouped_charges.setdefault(
            key,
            {
                "quantity": ZERO,
                "gross_total": ZERO,
                "subsidy_amount": ZERO,
                "total": ZERO,
                "subsidy_rate": individual_line.subsidy_rate,
                "charge_ids": [],
                "booking_references": [],
                "target_name": charge.family_member.full_name if charge.family_member is not None else "",
            },
        )
        group["quantity"] += charge.quantity
        group["gross_total"] += individual_line.gross_total
        group["subsidy_amount"] += individual_line.subsidy_amount
        group["total"] += individual_line.total
        group["charge_ids"].append(charge.pk)
        group["booking_references"].append(charge.booking_reference)

    lines = []
    for key, group in grouped_charges.items():
        occurred_on, _kind, description, unit_price, _subsidy_rate, _family_member_id = key
        charge_ids = ",".join(str(charge_id) for charge_id in group["charge_ids"])
        lines.append(
            SettlementLine(
                label=description,
                quantity=money(group["quantity"]),
                unit_price=money(unit_price),
                gross_total=money(group["gross_total"]),
                subsidy_rate=group["subsidy_rate"],
                subsidy_amount=money(group["subsidy_amount"]),
                total=money(group["total"]),
                source=f"charges:{charge_ids}",
                occurred_on=occurred_on,
                booking_references=tuple(group["booking_references"]),
                target_name=group["target_name"],
            )
        )
    return lines


def drink_charge_lines(
    participant: Participant,
    drink_entries: Iterable[DrinkEntry] | None = None,
) -> list[SettlementLine]:
    lines = []
    entries: Iterable[Mapping[str, Any]]
    if drink_entries is None:
        entries = (
            DrinkEntry.objects.filter(participant=participant)
            .values("drink", "unit_price", "foerdersatz")
            .annotate(quantity_sum=Sum("quantity"))
            .order_by("drink", "foerdersatz")
        )
    else:
        grouped_entries: dict[tuple[str, Decimal, Decimal], int] = {}
        for drink_entry in drink_entries:
            key = (drink_entry.drink, drink_entry.unit_price, drink_entry.foerdersatz)
            grouped_entries[key] = grouped_entries.get(key, 0) + drink_entry.quantity
        entries = [
            {
                "drink": drink,
                "unit_price": unit_price,
                "foerdersatz": subsidy_rate,
                "quantity_sum": quantity,
            }
            for (drink, unit_price, subsidy_rate), quantity in sorted(
                grouped_entries.items(),
                key=lambda item: (item[0][0], item[0][2], item[0][1]),
            )
        ]
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


def shared_expense_charge_lines(
    participant: Participant,
    allocations: Iterable[ExpenseAllocation] | None = None,
) -> list[SettlementLine]:
    lines = []
    if allocations is None:
        allocations = ExpenseAllocation.objects.filter(participant=participant).select_related("expense")
    for allocation in allocations:
        date_str = allocation.expense.paid_on.strftime("%d.%m.%Y") if allocation.expense.paid_on else ""
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
        .prefetch_related(
            Prefetch("charges", queryset=Charge.objects.select_related("family_member")),
            "family_members",
            Prefetch("payments", queryset=Payment.objects.filter(deleted_at__isnull=True)),
            "expenses",
            "drink_entries",
            "expense_allocations__expense",
        )
        .get(pk=participant.pk)
    )
    lines = (
        default_charge_lines(participant)
        + family_camp_flat_lines(
            participant,
            participant.family_members.all(),
            participant.camp.price_rules.filter(is_default=True),
        )
        + manual_charge_lines(participant)
        + drink_charge_lines(participant)
        + shared_expense_charge_lines(participant)
    )
    total_gross = money(sum((line.gross_total for line in lines), ZERO))
    total_subsidy = money(sum((line.subsidy_amount for line in lines), ZERO))
    total_due = money(sum((line.total for line in lines), ZERO))
    total_paid = money(participant.payments.filter(deleted_at__isnull=True).aggregate(total=Sum("amount"))["total"])
    total_advanced = money(
        Expense.objects.filter(
            participant=participant,
            reimbursable=True,
            status=Expense.Status.APPROVED,
        ).aggregate(total=Sum("amount"))["total"]
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


def calculate_participant_settlements(
    participants: Iterable[Participant],
) -> dict[int, SettlementResult]:
    """Calculate multiple participant settlements with a bounded query count.

    Args:
        participants: Persisted participants whose current settlement is needed.

    Returns:
        Settlement results keyed by participant ID. Duplicate inputs are loaded once.
    """
    participant_ids = list(dict.fromkeys(participant.pk for participant in participants if participant.pk is not None))
    if not participant_ids:
        return {}

    loaded_participants = (
        Participant.objects.filter(pk__in=participant_ids)
        .select_related("camp")
        .prefetch_related(
            Prefetch(
                "charges",
                queryset=(
                    Charge.objects.filter(deleted_at__isnull=True)
                    .select_related("family_member")
                    .order_by("created_at", "pk")
                ),
                to_attr="settlement_charges",
            ),
            Prefetch(
                "family_members",
                queryset=ParticipantFamilyMember.objects.order_by("last_name", "first_name", "pk"),
                to_attr="settlement_family_members",
            ),
            Prefetch(
                "drink_entries",
                queryset=DrinkEntry.objects.order_by("drink", "foerdersatz", "unit_price", "pk"),
                to_attr="settlement_drink_entries",
            ),
            Prefetch(
                "expense_allocations",
                queryset=ExpenseAllocation.objects.select_related("expense"),
                to_attr="settlement_expense_allocations",
            ),
            Prefetch(
                "payments",
                queryset=Payment.objects.filter(deleted_at__isnull=True),
                to_attr="settlement_payments",
            ),
            Prefetch(
                "expenses",
                queryset=Expense.objects.filter(
                    reimbursable=True,
                    status=Expense.Status.APPROVED,
                ),
                to_attr="settlement_advanced_expenses",
            ),
        )
    )
    participants_by_id = {participant.pk: participant for participant in loaded_participants}
    default_rules_by_camp: dict[int, list[PriceRule]] = {}
    for rule in PriceRule.objects.filter(
        camp_id__in={participant.camp_id for participant in participants_by_id.values()},
        is_default=True,
    ):
        default_rules_by_camp.setdefault(rule.camp_id, []).append(rule)

    results: dict[int, SettlementResult] = {}
    for participant_id in participant_ids:
        participant = participants_by_id.get(participant_id)
        if participant is None:
            continue
        prefetched_participant = cast(Any, participant)
        lines = (
            default_charge_lines(participant, default_rules_by_camp.get(participant.camp_id, ()))
            + family_camp_flat_lines(
                participant,
                prefetched_participant.settlement_family_members,
                default_rules_by_camp.get(participant.camp_id, ()),
            )
            + manual_charge_lines(participant, prefetched_participant.settlement_charges)
            + drink_charge_lines(participant, prefetched_participant.settlement_drink_entries)
            + shared_expense_charge_lines(participant, prefetched_participant.settlement_expense_allocations)
        )
        total_gross = money(sum((line.gross_total for line in lines), ZERO))
        total_subsidy = money(sum((line.subsidy_amount for line in lines), ZERO))
        total_due = money(sum((line.total for line in lines), ZERO))
        total_paid = money(sum((payment.amount for payment in prefetched_participant.settlement_payments), ZERO))
        total_advanced = money(
            sum((expense.amount for expense in prefetched_participant.settlement_advanced_expenses), ZERO)
        )
        results[participant_id] = SettlementResult(
            participant=participant,
            lines=lines,
            total_gross=total_gross,
            total_subsidy=total_subsidy,
            total_due=total_due,
            total_paid=total_paid,
            total_advanced=total_advanced,
            balance=money(total_due - total_paid - total_advanced),
        )
    return results


def calculate_camp_settlements(camp):
    participants = Participant.objects.filter(camp=camp, archived_at__isnull=True).order_by("last_name", "first_name")
    results_by_id = calculate_participant_settlements(participants)
    return list(results_by_id.values())


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
                "occurred_on": line.occurred_on.isoformat() if line.occurred_on else None,
                "booking_references": list(line.booking_references),
                "target_name": line.target_name,
            }
            for line in result.lines
        ],
    }


class _CostCenterExpenseDetail(TypedDict):
    paid_on: date | None
    created_at: datetime | None
    participant: Participant | None
    description: str
    amount: Decimal


def _cost_center_expense_snapshot(expense: Expense | _CostCenterExpenseDetail) -> dict[str, str]:
    """Serialize an ORM expense or a normalized subsidy expense detail."""
    paid_date: date | None
    if isinstance(expense, Expense):
        paid_date = expense.paid_on or expense.created_at.date()
        participant = expense.participant
        description = expense.description
        amount = expense.amount
    else:
        paid_date = expense["paid_on"]
        created_at = expense["created_at"]
        if paid_date is None and created_at is not None:
            paid_date = created_at.date()
        participant = expense["participant"]
        description = expense["description"]
        amount = expense["amount"]
    return {
        "paid_date": paid_date.isoformat() if paid_date else "",
        "applicant_name": participant.full_name if participant else "Unbekannt",
        "description": description,
        "amount": str(money(amount)),
    }


def _cost_center_snapshot_data(camp: Camp) -> list[dict[str, Any]]:
    evaluation = get_cost_center_evaluation(camp)
    snapshot: list[dict[str, Any]] = []
    for code, data in evaluation.items():
        snapshot.append(
            {
                "code": code,
                "label": data["label"],
                "income": str(money(data["income"])),
                "expense_total": str(money(data["expense_total"])),
                "balance": str(money(data["balance"])),
                "income_count": data["income_count"],
                "expense_count": data["expense_count"],
                "income_details": [
                    (
                        {
                            "meal_date": signup.meal_date.isoformat(),
                            "participant_name": signup.participant.full_name,
                            "family_member_name": signup.family_member.full_name if signup.family_member else "",
                            "description": signup.get_meal_display(),
                            "amount": str(money(signup.charge.total if signup.charge is not None else ZERO)),
                        }
                        if isinstance(signup, MealSignup)
                        else {
                            "meal_date": signup["date"].isoformat() if signup["date"] else "",
                            "participant_name": signup["participant"].full_name,
                            "family_member_name": signup.get("family_member_name", ""),
                            "description": signup["description"],
                            "amount": str(money(signup["total"])),
                        }
                    )
                    for signup in data["income_details"]
                ],
                "expense_details": [_cost_center_expense_snapshot(expense) for expense in data["expense_details"]],
            }
        )
    return snapshot


@transaction.atomic
def create_settlement_run(
    camp: Camp,
    calculated_by: Any,
    run_type: str = SettlementRun.RunType.MANUAL,
) -> SettlementRun:
    locked_camp = Camp.objects.select_for_update().get(pk=camp.pk)
    latest_version = locked_camp.settlement_runs.aggregate(value=Max("version"))["value"] or 0
    results = calculate_camp_settlements(locked_camp)
    run = SettlementRun.objects.create(
        camp=locked_camp,
        version=latest_version + 1,
        run_type=run_type,
        calculated_by=calculated_by,
        participant_count=len(results),
        total_gross=money(sum((result.total_gross for result in results), ZERO)),
        total_subsidy=money(sum((result.total_subsidy for result in results), ZERO)),
        total_due=money(sum((result.total_due for result in results), ZERO)),
        total_paid=money(sum((result.total_paid for result in results), ZERO)),
        total_advanced=money(sum((result.total_advanced for result in results), ZERO)),
        balance=money(sum((result.balance for result in results), ZERO)),
        cost_center_data=_cost_center_snapshot_data(locked_camp),
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


def _participant_kiosk_summary_from_result(result: SettlementResult) -> dict[str, Any]:
    return {
        "participant": result.participant.full_name,
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
                "occurred_on": line.occurred_on,
                "booking_references": line.booking_references,
            }
            for line in result.lines
        ],
    }


def participant_kiosk_summary(participant: Participant) -> dict[str, Any]:
    """Return one participant's current kiosk invoice summary."""
    return _participant_kiosk_summary_from_result(calculate_participant_settlement(participant))


def participant_kiosk_summaries(participants: Iterable[Participant]) -> dict[int, dict[str, Any]]:
    """Return current kiosk invoice summaries with queries independent of account count."""
    return {
        participant_id: _participant_kiosk_summary_from_result(result)
        for participant_id, result in calculate_participant_settlements(participants).items()
    }


@transaction.atomic
def approve_shared_expense(
    expense: Expense,
    approved_by: Any,
    participant_ids: list[int] | None = None,
    *,
    allocation_method: str | None = None,
    cost_center: str | None = None,
) -> None:
    """Approve a shared expense and atomically persist its allocation decision.

    Args:
        expense: Pending expense to approve.
        approved_by: User approving the expense.
        participant_ids: Participants selected for a direct allocation.
        allocation_method: Validated allocation method chosen by the approver.
        cost_center: Validated cost center chosen by the approver.

    Raises:
        ValidationError: If the expense is no longer pending or its allocation has no participants.
    """
    locked_expense = Expense.objects.select_for_update().get(pk=expense.pk)
    if locked_expense.status != Expense.Status.PENDING:
        raise ValidationError("Nur ausstehende Ausgaben können genehmigt werden.")

    if allocation_method is not None:
        locked_expense.allocation_method = allocation_method
    if cost_center is not None:
        locked_expense.cost_center = cost_center
    locked_expense.status = Expense.Status.APPROVED
    locked_expense.approved_by = approved_by
    locked_expense.approved_at = timezone.now()

    if locked_expense.allocation_method in (Expense.AllocationMethod.NONE, Expense.AllocationMethod.COST_CENTER):
        locked_expense.save(update_fields=["status", "approved_by", "approved_at", "allocation_method", "cost_center"])
        expense.status = locked_expense.status
        expense.approved_by = locked_expense.approved_by
        expense.approved_at = locked_expense.approved_at
        expense.allocation_method = locked_expense.allocation_method
        expense.cost_center = locked_expense.cost_center
        transaction.on_commit(partial(_notify_expense_status_by_id, locked_expense.pk))
        return

    participants = []
    if locked_expense.allocation_method == Expense.AllocationMethod.ALL_ACTIVE:
        participants = list(Participant.objects.filter(camp=locked_expense.camp, archived_at__isnull=True))
    elif locked_expense.allocation_method == Expense.AllocationMethod.SELECTED:
        if not participant_ids:
            raise ValidationError("Es wurden keine Teilnehmer für die Umlage ausgewählt.")
        participants = list(Participant.objects.filter(id__in=participant_ids, camp=locked_expense.camp))

    if not participants:
        raise ValidationError("Es konnten keine Teilnehmer für die Umlage ermittelt werden.")

    count = len(participants)
    base_amount_per_person = money(locked_expense.amount / Decimal(count))
    remainder = locked_expense.amount - (base_amount_per_person * count)

    allocations = []
    for p in participants:
        amount = base_amount_per_person
        if remainder > 0:
            amount += Decimal("0.01")
            remainder -= Decimal("0.01")
        elif remainder < 0:
            amount -= Decimal("0.01")
            remainder += Decimal("0.01")
        allocations.append(ExpenseAllocation(expense=locked_expense, participant=p, amount=amount))

    ExpenseAllocation.objects.bulk_create(allocations)
    locked_expense.save(update_fields=["status", "approved_by", "approved_at", "allocation_method", "cost_center"])
    expense.status = locked_expense.status
    expense.approved_by = locked_expense.approved_by
    expense.approved_at = locked_expense.approved_at
    expense.allocation_method = locked_expense.allocation_method
    expense.cost_center = locked_expense.cost_center
    transaction.on_commit(partial(_notify_expense_status_by_id, locked_expense.pk))


@transaction.atomic
def reject_shared_expense(expense: Expense, rejected_by: Any, rejection_reason: str = "") -> None:
    if expense.status != Expense.Status.PENDING:
        raise ValidationError("Nur ausstehende Ausgaben können abgelehnt werden.")
    expense.status = Expense.Status.REJECTED
    expense.approved_by = rejected_by
    expense.approved_at = timezone.now()
    expense.rejection_reason = rejection_reason
    expense.save(update_fields=["status", "approved_by", "approved_at", "rejection_reason"])
    transaction.on_commit(partial(_notify_expense_status_by_id, expense.pk))


def _notify_expense_status_by_id(expense_id: int) -> None:
    """Load a committed expense and enqueue its participant status notification."""
    from .notifications import notify_expense_status

    notify_expense_status(Expense.objects.select_related("participant").get(pk=expense_id))


def get_cost_center_evaluation(camp):
    evaluation = {
        code: {
            "label": label,
            "income": Decimal("0.00"),
            "expense_total": Decimal("0.00"),
            "balance": Decimal("0.00"),
            "income_count": 0,
            "expense_count": 0,
            "income_details": [],
            "expense_details": [],
        }
        for code, label in Expense.CostCenter.choices
    }

    CAMP_FLAT_COST_CENTERS = {
        Expense.CostCenter.FOOD_OTHER,
        Expense.CostCenter.TRAVEL,
        Expense.CostCenter.MATERIALS,
        Expense.CostCenter.RENT_OTHER,
    }

    evaluation["camp_flat"] = {
        "label": (
            "Lagerpauschale (Unterkunft/Verpflegung - sonstiges, Fahrtkosten, Verbrauchsmaterial, Miete/sonstiges)"
        ),
        "income": Decimal("0.00"),
        "expense_total": Decimal("0.00"),
        "balance": Decimal("0.00"),
        "income_count": 0,
        "expense_count": 0,
        "income_details": [],
        "expense_details": [],
    }

    evaluation["subsidies"] = {
        "label": "Förderungen",
        "income": Decimal("0.00"),
        "expense_total": Decimal("0.00"),
        "balance": Decimal("0.00"),
        "income_count": 0,
        "expense_count": 0,
        "income_details": [],
        "expense_details": [],
    }

    expenses = Expense.objects.filter(
        camp=camp,
        allocation_method=Expense.AllocationMethod.COST_CENTER,
        status=Expense.Status.APPROVED,
    ).select_related("participant")

    for exp in expenses:
        code = exp.cost_center or "without_cost_center"
        target_code = "camp_flat" if code in CAMP_FLAT_COST_CENTERS else code
        if target_code not in evaluation:
            evaluation[target_code] = {
                "label": "Ohne Kostenstelle",
                "income": Decimal("0.00"),
                "expense_total": Decimal("0.00"),
                "balance": Decimal("0.00"),
                "income_count": 0,
                "expense_count": 0,
                "income_details": [],
                "expense_details": [],
            }

        evaluation[target_code]["expense_total"] += exp.amount
        evaluation[target_code]["expense_count"] += 1
        evaluation[target_code]["expense_details"].append(exp)

    meal_cost_centers = {
        MealSignup.Meal.BREAKFAST: Expense.CostCenter.FOOD_BREAKFAST,
        MealSignup.Meal.DINNER: Expense.CostCenter.FOOD_DINNER,
    }
    meal_signups = (
        MealSignup.objects.filter(
            participant__camp=camp,
            status=MealSignup.Status.ACTIVE,
            charge__isnull=False,
            charge__deleted_at__isnull=True,
        )
        .select_related("participant", "family_member", "charge")
        .order_by("meal_date", "meal", "participant__last_name", "participant__first_name")
    )
    for signup in meal_signups:
        code = meal_cost_centers.get(signup.meal)
        if code is None or signup.charge is None:
            continue
        amount = signup.charge.total
        evaluation[code]["income"] += amount
        evaluation[code]["income_count"] += 1
        evaluation[code]["income_details"].append(signup)

    # 1. Manual CAMP_FLAT charges
    camp_flat_charges = (
        Charge.objects.filter(
            participant__camp=camp,
            kind=Charge.Kind.CAMP_FLAT,
            deleted_at__isnull=True,
        )
        .select_related("participant")
        .order_by("participant__last_name", "participant__first_name", "occurred_on")
    )
    for charge in camp_flat_charges:
        evaluation["camp_flat"]["income"] += charge.total
        evaluation["camp_flat"]["income_count"] += 1
        evaluation["camp_flat"]["income_details"].append(
            {
                "date": charge.occurred_on,
                "participant": charge.participant,
                "description": charge.description or charge.get_kind_display(),
                "total": charge.total,
            }
        )

    # 2. Automated CAMP_FLAT from rules
    active_participants = (
        Participant.objects.filter(
            camp=camp,
            status__in=[Participant.Status.REGISTERED, Participant.Status.ACTIVE, Participant.Status.SETTLED],
        )
        .select_related("camp")
        .prefetch_related("family_members")
    )
    default_rules = list(PriceRule.objects.filter(camp=camp, is_default=True))
    camp_flat_rules = [rule for rule in default_rules if rule.kind == PriceRule.Kind.CAMP_FLAT]

    for participant in active_participants:
        matching_rules = [
            rule
            for rule in camp_flat_rules
            if rule.camp_flat_duration == participant_camp_flat_duration(participant)
            and rule.camp_flat_role == participant_camp_flat_role(participant)
        ]
        if not matching_rules:
            matching_rules = [
                rule for rule in camp_flat_rules if rule.camp_flat_duration == "" and rule.camp_flat_role == ""
            ]

        for rule in matching_rules:
            if not _rule_applies(rule, participant):
                continue
            gross = rule.unit_price

            evaluation["camp_flat"]["income"] += gross
            evaluation["camp_flat"]["income_count"] += 1
            evaluation["camp_flat"]["income_details"].append(
                {
                    "date": None,
                    "participant": participant,
                    "description": f"{rule.name} (Automatisch)",
                    "total": gross,
                }
            )

        for line in family_camp_flat_lines(participant, participant.family_members.all(), default_rules):
            evaluation["camp_flat"]["income"] += line.gross_total
            evaluation["camp_flat"]["income_count"] += 1
            evaluation["camp_flat"]["income_details"].append(
                {
                    "date": None,
                    "participant": participant,
                    "family_member_name": line.target_name,
                    "description": f"{line.label} (Automatisch)",
                    "total": line.gross_total,
                }
            )

    # 3. Donations for Subsidies
    donation_charges = (
        Charge.objects.filter(
            participant__camp=camp,
            kind=Charge.Kind.DONATION,
            deleted_at__isnull=True,
        )
        .select_related("participant")
        .order_by("participant__last_name", "participant__first_name", "occurred_on")
    )
    for charge in donation_charges:
        evaluation["subsidies"]["income"] += charge.total
        evaluation["subsidies"]["income_count"] += 1
        evaluation["subsidies"]["income_details"].append(
            {
                "date": charge.occurred_on,
                "participant": charge.participant,
                "description": charge.description or "Spende",
                "total": charge.total,
            }
        )

    # 4. Calculate Subsidies Given
    settlements = calculate_participant_settlements(active_participants)
    for res in settlements.values():
        for line in res.lines:
            if line.subsidy_amount > 0:
                evaluation["subsidies"]["expense_total"] += line.subsidy_amount
                evaluation["subsidies"]["expense_count"] += 1
                evaluation["subsidies"]["expense_details"].append(
                    {
                        "paid_on": line.occurred_on,
                        "created_at": None,
                        "participant": res.participant,
                        "description": f"Förderung für {line.label}",
                        "amount": line.subsidy_amount,
                    }
                )

    for data in evaluation.values():
        data["balance"] = data["income"] - data["expense_total"]

    return {code: data for code, data in evaluation.items() if data["income_count"] or data["expense_count"]}


def lock_camp_price_rules_for_update(camp: Camp | int) -> tuple[Camp, dict[int, PriceRule]]:
    """Lock a camp and all of its price rules in the global mutation order.

    The caller must already be inside ``transaction.atomic()`` and keep every
    PriceRule write plus dependent synchronization inside that transaction.

    Args:
        camp: Camp instance or primary key whose price rules will be mutated.

    Returns:
        The locked camp and its locked price rules keyed by primary key.
    """
    camp_id = camp.pk if isinstance(camp, Camp) else camp
    locked_camp = Camp.objects.select_for_update(of=("self",)).get(pk=camp_id)
    locked_rules = {
        rule.pk: rule
        for rule in PriceRule.objects.select_for_update(of=("self",)).filter(camp=locked_camp).order_by("pk")
    }
    return locked_camp, locked_rules


@transaction.atomic
def sync_meal_signup_charges_for_camp(camp: Camp) -> int:
    """Synchronize unfinalized future meal signups with current meal rules.

    Archived rules, historical bookings, and deleted charges are intentionally
    left unchanged. Settlement snapshots remain immutable copies and do not
    lock their mutable source bookings.
    """
    camp, locked_rules = lock_camp_price_rules_for_update(camp)
    all_rules = [rule for rule in locked_rules.values() if rule.kind == PriceRule.Kind.MEAL and not rule.is_archived]
    if not all_rules:
        return 0

    updated_count = 0
    today = timezone.localdate()
    signups = MealSignup.objects.filter(participant__camp=camp, status=MealSignup.Status.ACTIVE).select_related(
        "charge", "family_member", "participant"
    )
    for signup in signups:
        if signup.meal_date < today:
            continue
        charge = signup.charge
        if charge is not None and charge.deleted_at is not None:
            continue
        target = signup.family_member or signup.participant
        is_companion = (
            signup.family_member.role == ParticipantFamilyMember.Role.COMPANION
            if signup.family_member is not None
            else signup.participant.is_companion
        )
        rule = _resolve_meal_price_rule_from_rules(
            all_rules,
            signup.meal,
            signup.meal_date,
            is_child=target.is_child,
            is_companion=is_companion,
        )
        if rule is None:
            continue

        signup_changed = False
        if signup.foerdersatz != rule.foerdersatz:
            signup.foerdersatz = rule.foerdersatz
            signup_changed = True

        if signup_changed:
            signup.save(update_fields=["foerdersatz", "updated_at"])
            updated_count += 1

        if charge is not None:
            charge_changed = False
            if charge.foerdersatz != rule.foerdersatz:
                charge.foerdersatz = rule.foerdersatz
                charge_changed = True
            if charge.unit_price != rule.unit_price:
                charge.unit_price = rule.unit_price
                charge_changed = True
            if charge_changed:
                charge.save(update_fields=["foerdersatz", "unit_price", "updated_at"])

    return updated_count
