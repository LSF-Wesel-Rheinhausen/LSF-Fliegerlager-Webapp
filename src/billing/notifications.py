import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from pywebpush import WebPushException, webpush

from .models import (
    Camp,
    Charge,
    Expense,
    MealOrder,
    MealSignup,
    Participant,
    ParticipantBookingLink,
    PushMessage,
    Shift,
    ShiftAssignment,
)
from .permissions import ADMIN_GROUP, EDITOR_GROUP, HUEBERS_GROUP

logger = logging.getLogger(__name__)

PARTICIPANT_CATEGORIES: dict[str, str] = {
    "shifts": "Dienste und Diensttausch",
    "booking_links": "Verknüpfungen und Buchungen",
    "meal_deadlines": "Essensfristen",
    "expense_status": "Status eigener Auslagen",
}
ADMIN_CATEGORIES: dict[str, str] = {
    "expenses_admin": "Neue Auslagenanträge",
    "open_shifts_admin": "Offene Dienste",
    "meal_orders_admin": "Offene Essensbestellungen",
}
ALL_CATEGORIES = {**PARTICIPANT_CATEGORIES, **ADMIN_CATEGORIES}
RETRY_DELAYS = (60, 300, 1800, 7200, 21600)
User = get_user_model()


@dataclass(frozen=True)
class PushDeliveryResult:
    """Summarize one bounded worker delivery batch."""

    sent: int = 0
    retried: int = 0
    failed: int = 0
    removed_subscriptions: int = 0


def allowed_categories(*, participant_owner: bool) -> dict[str, str]:
    """Return the category menu for a participant or administrative owner."""
    return PARTICIPANT_CATEGORIES if participant_owner else ADMIN_CATEGORIES


def queue_participant_notification(
    participant: Participant,
    *,
    category: str,
    title: str,
    body: str,
    target_url: str,
    dedupe_key: str,
    scheduled_for: Any | None = None,
) -> int:
    """Queue one idempotent message for each eligible participant device."""
    subscriptions = [
        subscription
        for subscription in participant.push_subscriptions.filter(is_active=True)
        if category in subscription.categories
    ]
    return _queue_for_subscriptions(
        subscriptions,
        category=category,
        title=title,
        body=body,
        target_url=target_url,
        dedupe_key=dedupe_key,
        scheduled_for=scheduled_for,
    )


def queue_user_notification(
    user: Any,
    *,
    category: str,
    title: str,
    body: str,
    target_url: str,
    dedupe_key: str,
    scheduled_for: Any | None = None,
) -> int:
    """Queue one idempotent message for each eligible administrative device."""
    subscriptions = [
        subscription
        for subscription in user.push_subscriptions.filter(is_active=True)
        if category in subscription.categories
    ]
    return _queue_for_subscriptions(
        subscriptions,
        category=category,
        title=title,
        body=body,
        target_url=target_url,
        dedupe_key=dedupe_key,
        scheduled_for=scheduled_for,
    )


def _queue_for_subscriptions(
    subscriptions: Any,
    *,
    category: str,
    title: str,
    body: str,
    target_url: str,
    dedupe_key: str,
    scheduled_for: Any | None,
) -> int:
    if not settings.WEB_PUSH_ENABLED:
        return 0
    if category not in ALL_CATEGORIES:
        raise ValueError("Unsupported push category")
    if not target_url.startswith("/") or target_url.startswith("//"):
        raise ValueError("Push target URL must be a same-origin relative path")
    due_at = scheduled_for or timezone.now()
    created = 0
    for subscription in subscriptions:
        _message, was_created = PushMessage.objects.get_or_create(
            subscription=subscription,
            dedupe_key=dedupe_key,
            defaults={
                "category": category,
                "title": title[:120],
                "body": body[:300],
                "target_url": target_url[:500],
                "scheduled_for": due_at,
                "next_attempt_at": due_at,
            },
        )
        created += int(was_created)
    return created


def _administrative_users(*, include_meal_managers: bool = False) -> Any:
    group_names = [ADMIN_GROUP, EDITOR_GROUP]
    if include_meal_managers:
        group_names.append(HUEBERS_GROUP)
    return User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(groups__name__in=group_names)).distinct()


def notify_expense_submitted(expense: Expense) -> None:
    """Notify administrators that a participant expense awaits review."""
    participant = expense.participant
    if participant is None:
        return
    for user in _administrative_users():
        queue_user_notification(
            user,
            category="expenses_admin",
            title="Neue Auslage",
            body=f"{participant.full_name} hat eine Auslage über {expense.amount:.2f} EUR eingereicht.",
            target_url=f"/expenses/{expense.pk}/approve/",
            dedupe_key=f"expense:{expense.pk}:pending",
        )


def notify_expense_status(expense: Expense) -> None:
    """Notify the requesting participant about an approved or rejected expense."""
    participant = expense.participant
    if participant is None or expense.status not in {Expense.Status.APPROVED, Expense.Status.REJECTED}:
        return
    status_label = "genehmigt" if expense.status == Expense.Status.APPROVED else "abgelehnt"
    amount = f"{expense.amount:.2f}".replace(".", ",")
    queue_participant_notification(
        participant,
        category="expense_status",
        title=f"Auslage {status_label}",
        body=f"Deine Auslage über {amount} EUR wurde {status_label}.",
        target_url="/kiosk/",
        dedupe_key=f"expense:{expense.pk}:{expense.status}",
    )


def notify_booking_link(link: ParticipantBookingLink, *, event: str, actor: Participant) -> None:
    """Notify the participant affected by a booking-link state change."""
    if event == "invited":
        recipient = link.invitee
        title = "Neue Buchungseinladung"
        body = f"{link.inviter.full_name} möchte Buchungen mit dir verknüpfen."
    else:
        recipient = link.invitee if actor.pk == link.inviter_id else link.inviter
        labels = {"accepted": "angenommen", "declined": "abgelehnt", "revoked": "aufgelöst"}
        if event not in labels:
            raise ValueError("Unsupported booking-link event")
        title = "Buchungsverknüpfung geändert"
        body = f"{actor.full_name} hat die Buchungsverknüpfung {labels[event]}."
    queue_participant_notification(
        recipient,
        category="booking_links",
        title=title,
        body=body,
        target_url="/kiosk/",
        dedupe_key=f"booking-link:{link.pk}:{event}",
    )


def notify_linked_booking(charge: Charge, *, cancelled: bool) -> None:
    """Notify a participant when another linked participant changes their booking."""
    booking_actor = charge.kiosk_booked_by
    if booking_actor is None or booking_actor.pk == charge.participant_id:
        return
    action = "storniert" if cancelled else "gebucht"
    queue_participant_notification(
        charge.participant,
        category="booking_links",
        title=f"Buchung {action}",
        body=f"{booking_actor.full_name} hat {charge.description} für dich {action}.",
        target_url="/kiosk/",
        dedupe_key=f"linked-booking:{charge.pk}:{'cancelled' if cancelled else 'created'}",
    )


def notify_shift_exchange(
    assignment: ShiftAssignment,
    *,
    event: str,
    actor: Participant,
    previous_participant: Participant | None = None,
) -> None:
    """Notify eligible participants about an offered or completed shift exchange."""
    if event == "offered":
        for participant in assignment.shift.camp.participants.filter(archived_at__isnull=True).exclude(pk=actor.pk):
            queue_participant_notification(
                participant,
                category="shifts",
                title="Dienst zum Tausch angeboten",
                body=f"{actor.full_name} bietet {assignment.shift.name} am {assignment.shift.date:%d.%m.%Y} an.",
                target_url="/kiosk/shifts/",
                dedupe_key=f"shift:{assignment.shift_id}:exchange:{assignment.pk}:offered",
            )
        return
    if event == "taken" and previous_participant is not None:
        queue_participant_notification(
            previous_participant,
            category="shifts",
            title="Dienst übernommen",
            body=f"{actor.full_name} hat deinen Dienst {assignment.shift.name} übernommen.",
            target_url="/kiosk/shifts/",
            dedupe_key=f"shift:{assignment.shift_id}:exchange:{assignment.pk}:taken",
        )
        return
    raise ValueError("Unsupported shift exchange event")


def _reminder_time(shift_date: Any, start_time: Any | None) -> tuple[Any, Any]:
    timezone_value = timezone.get_current_timezone()
    if start_time is None:
        event_at = timezone.make_aware(datetime.combine(shift_date, time(23, 59)), timezone_value)
        due_at = timezone.make_aware(datetime.combine(shift_date, time(9, 0)), timezone_value)
        return due_at, event_at
    event_at = timezone.make_aware(datetime.combine(shift_date, start_time), timezone_value)
    return event_at - timedelta(hours=1), event_at


def generate_scheduled_notifications(*, now: Any | None = None) -> int:
    """Create all currently due shift and meal reminders idempotently."""
    current = now or timezone.now()
    today = timezone.localdate(current)
    created = 0
    assignments = ShiftAssignment.objects.select_related("participant", "shift", "shift__camp").filter(
        shift__date__gte=today,
        shift__date__lte=today + timedelta(days=1),
        participant__archived_at__isnull=True,
    )
    for assignment in assignments:
        due_at, event_at = _reminder_time(assignment.shift.date, assignment.shift.start_time)
        if due_at <= current < event_at:
            created += queue_participant_notification(
                assignment.participant,
                category="shifts",
                title="Dienst beginnt bald",
                body=f"{assignment.shift.name} beginnt in einer Stunde.",
                target_url="/kiosk/shifts/",
                dedupe_key=(f"shift:{assignment.shift_id}:participant:{assignment.participant_id}:reminder"),
                scheduled_for=due_at,
            )

    shifts = Shift.objects.select_related("camp").filter(date__gte=today, date__lte=today + timedelta(days=1))
    for shift in shifts:
        due_at, event_at = _reminder_time(shift.date, shift.start_time)
        if due_at > current or current >= event_at or shift.assignments.count() >= shift.required_slots:
            continue
        for user in _administrative_users():
            created += queue_user_notification(
                user,
                category="open_shifts_admin",
                title="Dienst noch nicht besetzt",
                body=f"{shift.name} ist noch nicht vollständig besetzt.",
                target_url=f"/camps/{shift.camp_id}/shifts/",
                dedupe_key=f"shift:{shift.pk}:open",
                scheduled_for=due_at,
            )

    meal_date = today + timedelta(days=1)
    for camp in Camp.objects.filter(is_active=True):
        cutoff_at = timezone.make_aware(datetime.combine(today, camp.meal_booking_cutoff_time))
        due_at = cutoff_at - timedelta(hours=1)
        if not due_at <= current < cutoff_at:
            continue
        booked_ids = MealSignup.objects.filter(
            participant__camp=camp,
            meal_date=meal_date,
            meal=MealSignup.Meal.DINNER,
            status=MealSignup.Status.ACTIVE,
            family_member__isnull=True,
        ).values_list("participant_id", flat=True)
        for participant in camp.participants.filter(archived_at__isnull=True).exclude(pk__in=booked_ids):
            created += queue_participant_notification(
                participant,
                category="meal_deadlines",
                title="Essensfrist endet bald",
                body=f"Abendessen für morgen kann noch bis {camp.meal_booking_cutoff_time:%H:%M} gebucht werden.",
                target_url="/kiosk/#meal-calendar",
                dedupe_key=f"meal:{camp.pk}:{meal_date}:participant:{participant.pk}:deadline",
                scheduled_for=due_at,
            )
        if not MealOrder.objects.filter(camp=camp, meal_date=meal_date).exists():
            for user in _administrative_users(include_meal_managers=True):
                created += queue_user_notification(
                    user,
                    category="meal_orders_admin",
                    title="Essensbestellung noch offen",
                    body=f"Die Bestellung für {meal_date:%d.%m.%Y} wurde noch nicht als versandt markiert.",
                    target_url=f"/camps/{camp.pk}/meals/",
                    dedupe_key=f"meal-order:{camp.pk}:{meal_date}:open",
                    scheduled_for=due_at,
                )
    return created


def send_due_push_messages(*, batch_size: int = 50) -> PushDeliveryResult:
    """Deliver one bounded outbox batch without exposing push capabilities in logs."""
    now = timezone.now()
    messages = list(
        PushMessage.objects.select_related("subscription")
        .filter(status=PushMessage.Status.PENDING, next_attempt_at__lte=now)
        .order_by("next_attempt_at", "pk")[:batch_size]
    )
    sent = retried = failed = removed = 0
    for message in messages:
        subscription = message.subscription
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=json.dumps(
                    {
                        "title": message.title,
                        "body": message.body,
                        "url": message.target_url,
                        "tag": message.dedupe_key,
                    },
                    ensure_ascii=False,
                ),
                vapid_private_key=settings.WEB_PUSH_VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.WEB_PUSH_VAPID_SUBJECT},
                ttl=86400,
            )
        except WebPushException as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            if status_code in {404, 410}:
                subscription.delete()
                removed += 1
                continue
            message.attempts += 1
            message.last_error_code = str(status_code or "delivery_error")[:40]
            if message.attempts >= len(RETRY_DELAYS):
                message.status = PushMessage.Status.FAILED
                failed += 1
            else:
                message.next_attempt_at = now + timedelta(seconds=RETRY_DELAYS[message.attempts - 1])
                retried += 1
            message.save(update_fields=["attempts", "last_error_code", "status", "next_attempt_at", "updated_at"])
            logger.warning(
                "Push delivery failed",
                extra={"push_message_id": message.pk, "status_code": status_code, "attempt": message.attempts},
            )
            continue

        with transaction.atomic():
            message.status = PushMessage.Status.SENT
            message.sent_at = now
            message.attempts += 1
            message.last_error_code = ""
            message.save(update_fields=["status", "sent_at", "attempts", "last_error_code", "updated_at"])
            subscription.last_success_at = now
            subscription.failure_count = 0
            subscription.save(update_fields=["last_success_at", "failure_count", "updated_at"])
        sent += 1
    return PushDeliveryResult(sent=sent, retried=retried, failed=failed, removed_subscriptions=removed)


def cleanup_push_messages(*, now: Any | None = None) -> int:
    """Delete completed outbox metadata after the documented retention period."""
    cutoff = (now or timezone.now()) - timedelta(days=30)
    deleted, _details = PushMessage.objects.filter(
        status__in=[PushMessage.Status.SENT, PushMessage.Status.FAILED],
        updated_at__lt=cutoff,
    ).delete()
    return deleted
