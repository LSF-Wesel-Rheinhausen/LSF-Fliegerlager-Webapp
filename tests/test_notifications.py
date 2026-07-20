import hashlib
import json
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from pywebpush import WebPushException

from billing.models import (
    Charge,
    Expense,
    MealSignup,
    ParticipantBookingLink,
    PushMessage,
    PushSubscription,
    Shift,
    ShiftAssignment,
)
from billing.notifications import (
    generate_scheduled_notifications,
    notify_booking_link,
    notify_expense_status,
    notify_expense_submitted,
    notify_linked_booking,
    queue_participant_notification,
    send_due_push_messages,
)
from billing.services import approve_shared_expense
from billing.views import KIOSK_MODE_SESSION_KEY, KIOSK_PARTICIPANT_SESSION_KEY
from tests.factories import CampFactory, ParticipantFactory, UserFactory


@pytest.fixture(autouse=True)
def enable_web_push(settings):
    settings.WEB_PUSH_ENABLED = True
    settings.WEB_PUSH_VAPID_PUBLIC_KEY = "test-public-key"
    settings.WEB_PUSH_VAPID_PRIVATE_KEY = "test-private-key"
    settings.WEB_PUSH_VAPID_SUBJECT = "mailto:test@example.test"


def subscription_payload(endpoint: str = "https://push.example.test/device") -> dict:
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": "public-browser-key", "auth": "auth-secret"},
        "device_name": "Privates Telefon",
        "categories": ["shifts", "meal_deadlines"],
    }


@pytest.mark.django_db
def test_push_subscription_requires_exactly_one_owner():
    participant = ParticipantFactory()
    user = UserFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        PushSubscription.objects.create(
            endpoint="https://push.example.test/no-owner",
            p256dh="key",
            auth="secret",
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        PushSubscription.objects.create(
            user=user,
            participant=participant,
            endpoint="https://push.example.test/two-owners",
            p256dh="key",
            auth="secret",
        )


@pytest.mark.django_db
def test_admin_can_create_and_update_own_push_subscription(client):
    user = UserFactory()
    client.force_login(user)

    payload = subscription_payload()
    payload["categories"] = ["expenses_admin"]
    response = client.post(
        reverse("notification-subscribe"),
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 201
    subscription = PushSubscription.objects.get(user=user)
    assert subscription.participant_id is None
    assert subscription.device_name == "Privates Telefon"
    assert subscription.categories == ["expenses_admin"]
    assert response.json()["device"] == {
        "id": subscription.pk,
        "device_name": "Privates Telefon",
        "last_success_at": None,
        "endpoint_fingerprint": hashlib.sha256(payload["endpoint"].encode()).hexdigest(),
    }

    payload = subscription_payload()
    payload["device_name"] = "Laptop"
    payload["categories"] = ["meal_orders_admin"]
    response = client.post(
        reverse("notification-subscribe"),
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.device_name == "Laptop"
    assert subscription.categories == ["meal_orders_admin"]
    assert response.json()["device"]["device_name"] == "Laptop"


@pytest.mark.django_db
def test_private_participant_can_subscribe_but_central_endpoint_does_not_exist(client):
    participant = ParticipantFactory()
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = "private"
    session.save()

    response = client.post(
        reverse("kiosk-notification-subscribe"),
        data=json.dumps(subscription_payload()),
        content_type="application/json",
    )

    assert response.status_code == 201
    assert PushSubscription.objects.filter(participant=participant, user__isnull=True).exists()
    assert client.get("/central/kiosk/notifications/").status_code == 404


@pytest.mark.django_db
def test_subscription_rejects_invalid_endpoint_and_category(client):
    user = UserFactory()
    client.force_login(user)
    payload = subscription_payload("http://push.example.test/insecure")
    payload["categories"] = ["unknown"]

    response = client.post(
        reverse("notification-subscribe"),
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert PushSubscription.objects.count() == 0


@pytest.mark.django_db
def test_disabled_web_push_rejects_new_subscriptions(client, settings):
    settings.WEB_PUSH_ENABLED = False
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("notification-subscribe"),
        data=json.dumps(subscription_payload()),
        content_type="application/json",
    )

    assert response.status_code == 503
    assert PushSubscription.objects.count() == 0


@pytest.mark.django_db
def test_endpoint_cannot_silently_move_to_another_owner(client):
    first = UserFactory()
    second = UserFactory()
    PushSubscription.objects.create(
        user=first,
        endpoint="https://push.example.test/device",
        p256dh="key",
        auth="secret",
        categories=["shifts"],
    )
    client.force_login(second)

    payload = subscription_payload()
    payload["categories"] = ["expenses_admin"]
    response = client.post(
        reverse("notification-subscribe"),
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 409
    assert PushSubscription.objects.get().user == first


@pytest.mark.django_db
def test_queue_notification_honors_category_and_deduplicates():
    participant = ParticipantFactory()
    enabled = PushSubscription.objects.create(
        participant=participant,
        endpoint="https://push.example.test/enabled",
        p256dh="key",
        auth="secret",
        categories=["shifts"],
    )
    PushSubscription.objects.create(
        participant=participant,
        endpoint="https://push.example.test/disabled",
        p256dh="key",
        auth="secret",
        categories=["meal_deadlines"],
    )

    queue_participant_notification(
        participant,
        category="shifts",
        title="Dienst beginnt bald",
        body="Start in einer Stunde",
        target_url="/kiosk/shifts/",
        dedupe_key="shift:1:reminder",
    )
    queue_participant_notification(
        participant,
        category="shifts",
        title="Dienst beginnt bald",
        body="Start in einer Stunde",
        target_url="/kiosk/shifts/",
        dedupe_key="shift:1:reminder",
    )

    message = PushMessage.objects.get()
    assert message.subscription == enabled
    assert message.target_url == "/kiosk/shifts/"


@pytest.mark.django_db
@patch("billing.notifications.webpush")
def test_worker_sends_due_message_and_records_success(webpush):
    subscription = PushSubscription.objects.create(
        user=UserFactory(),
        endpoint="https://push.example.test/device",
        p256dh="key",
        auth="secret",
        categories=["expenses_admin"],
    )
    message = PushMessage.objects.create(
        subscription=subscription,
        category="expenses_admin",
        title="Neue Auslage",
        body="Eine Auslage wartet auf Bearbeitung.",
        target_url="/camps/",
        dedupe_key="expense:1:pending",
        scheduled_for=timezone.now() - timedelta(seconds=1),
    )

    result = send_due_push_messages()

    assert result.sent == 1
    message.refresh_from_db()
    subscription.refresh_from_db()
    assert message.status == PushMessage.Status.SENT
    assert message.sent_at is not None
    assert subscription.last_success_at is not None
    assert webpush.call_count == 1


@pytest.mark.django_db
@patch("billing.notifications.webpush")
def test_worker_deletes_gone_subscription(webpush):
    class GoneResponse:
        status_code = 410

    webpush.side_effect = WebPushException("gone", response=GoneResponse())
    subscription = PushSubscription.objects.create(
        user=UserFactory(),
        endpoint="https://push.example.test/gone",
        p256dh="key",
        auth="secret",
        categories=["expenses_admin"],
    )
    PushMessage.objects.create(
        subscription=subscription,
        category="expenses_admin",
        title="Neue Auslage",
        body="Wartet.",
        target_url="/camps/",
        dedupe_key="expense:2:pending",
        scheduled_for=timezone.now() - timedelta(seconds=1),
    )

    result = send_due_push_messages()

    assert result.removed_subscriptions == 1
    assert not PushSubscription.objects.filter(pk=subscription.pk).exists()


@pytest.mark.django_db
def test_notification_settings_show_only_current_owners_devices(client):
    user = UserFactory()
    other = UserFactory()
    PushSubscription.objects.create(
        user=user,
        endpoint="https://push.example.test/mine",
        p256dh="key",
        auth="secret",
        device_name="Mein Laptop",
        categories=["expenses_admin"],
    )
    PushSubscription.objects.create(
        user=other,
        endpoint="https://push.example.test/other",
        p256dh="key",
        auth="secret",
        device_name="Fremdes Gerät",
        categories=["expenses_admin"],
    )
    client.force_login(user)

    response = client.get(reverse("notification-settings"))

    assert response.status_code == 200
    assert b"Mein Laptop" in response.content
    assert b"Fremdes Ger\xc3\xa4t" not in response.content
    assert hashlib.sha256(b"https://push.example.test/mine").hexdigest().encode() in response.content
    assert b"https://push.example.test/mine" not in response.content


@pytest.mark.django_db
def test_owner_can_queue_test_message_for_one_device(client):
    user = UserFactory()
    subscription = PushSubscription.objects.create(
        user=user,
        endpoint="https://push.example.test/test-device",
        p256dh="key",
        auth="secret",
        categories=["expenses_admin"],
    )
    client.force_login(user)

    response = client.post(reverse("notification-test", kwargs={"subscription_id": subscription.pk}))

    assert response.status_code == 202
    assert PushMessage.objects.filter(subscription=subscription, title="Testbenachrichtigung").exists()


@pytest.mark.django_db
def test_expense_events_notify_admin_and_requesting_participant():
    participant = ParticipantFactory()
    admin = UserFactory(is_superuser=True)
    PushSubscription.objects.create(
        user=admin,
        endpoint="https://push.example.test/admin",
        p256dh="key",
        auth="secret",
        categories=["expenses_admin"],
    )
    PushSubscription.objects.create(
        participant=participant,
        endpoint="https://push.example.test/participant",
        p256dh="key",
        auth="secret",
        categories=["expense_status"],
    )
    expense = Expense.objects.create(
        camp=participant.camp,
        participant=participant,
        category="Einkauf",
        description="Schrauben",
        amount=Decimal("12.50"),
        paid_on=date(2026, 7, 20),
        reimbursable=True,
    )

    notify_expense_submitted(expense)
    expense.status = Expense.Status.APPROVED
    notify_expense_status(expense)

    messages = PushMessage.objects.order_by("category")
    assert [message.category for message in messages] == ["expense_status", "expenses_admin"]
    assert "12,50" in messages.get(category="expense_status").body


@pytest.mark.django_db
def test_scheduled_shift_reminder_uses_one_hour_lead_and_deduplicates():
    now = timezone.make_aware(timezone.datetime(2026, 7, 20, 11, 0))
    participant = ParticipantFactory()
    PushSubscription.objects.create(
        participant=participant,
        endpoint="https://push.example.test/shift",
        p256dh="key",
        auth="secret",
        categories=["shifts"],
    )
    shift = Shift.objects.create(
        camp=participant.camp,
        name="Mittagsdienst",
        date=now.date(),
        start_time=time(12, 0),
        required_slots=1,
    )
    ShiftAssignment.objects.create(shift=shift, participant=participant)

    generate_scheduled_notifications(now=now)
    generate_scheduled_notifications(now=now + timedelta(minutes=5))

    message = PushMessage.objects.get(category="shifts")
    assert "Mittagsdienst" in message.body
    assert message.dedupe_key == f"shift:{shift.pk}:participant:{participant.pk}:reminder"


@pytest.mark.django_db
def test_scheduled_meal_deadline_skips_existing_signup():
    now = timezone.make_aware(timezone.datetime(2026, 7, 20, 11, 0))
    camp = ParticipantFactory().camp
    camp.meal_booking_cutoff_time = time(12, 0)
    camp.is_active = True
    camp.save(update_fields=["meal_booking_cutoff_time", "is_active"])
    missing = ParticipantFactory(camp=camp)
    booked = ParticipantFactory(camp=camp)
    for index, participant in enumerate((missing, booked), start=1):
        PushSubscription.objects.create(
            participant=participant,
            endpoint=f"https://push.example.test/meal-{index}",
            p256dh="key",
            auth="secret",
            categories=["meal_deadlines"],
        )
    MealSignup.objects.create(
        participant=booked,
        meal_date=now.date() + timedelta(days=1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        status=MealSignup.Status.ACTIVE,
    )

    generate_scheduled_notifications(now=now)

    message = PushMessage.objects.get(category="meal_deadlines")
    assert message.subscription.participant == missing
    assert "12:00" in message.body


@pytest.mark.django_db
def test_booking_link_and_linked_booking_events_notify_the_other_participant():
    inviter = ParticipantFactory()
    invitee = ParticipantFactory(camp=inviter.camp)
    PushSubscription.objects.create(
        participant=invitee,
        endpoint="https://push.example.test/invitee",
        p256dh="key",
        auth="secret",
        categories=["booking_links"],
    )
    link = ParticipantBookingLink.objects.create(inviter=inviter, invitee=invitee)

    notify_booking_link(link, event="invited", actor=inviter)
    charge = Charge.objects.create(
        participant=invitee,
        kiosk_booked_by=inviter,
        kind=Charge.Kind.DRINK,
        description="Wasser",
        quantity=1,
        unit_price=Decimal("1.50"),
    )
    notify_linked_booking(charge, actor=inviter, cancelled=False)

    assert PushMessage.objects.filter(category="booking_links").count() == 2
    assert PushMessage.objects.filter(body__contains="Wasser").exists()


@pytest.mark.django_db
def test_linked_booking_cancellation_notifies_original_booker_with_actual_actor():
    booker = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    cancelling_participant = ParticipantFactory(
        camp=booker.camp,
        first_name="Grace",
        last_name="Hopper",
    )
    subscription = PushSubscription.objects.create(
        participant=booker,
        endpoint="https://push.example.test/booker",
        p256dh="key",
        auth="secret",
        categories=["booking_links"],
    )
    charge = Charge.objects.create(
        participant=cancelling_participant,
        kiosk_booked_by=booker,
        kind=Charge.Kind.DRINK,
        description="Wasser",
        quantity=1,
        unit_price=Decimal("1.50"),
    )

    notify_linked_booking(charge, actor=cancelling_participant, cancelled=True)

    message = PushMessage.objects.get()
    assert message.subscription == subscription
    assert message.body == "Grace Hopper hat Wasser für dich storniert."


@pytest.mark.django_db
def test_linked_participant_quick_cancellation_passes_current_actor(
    client,
    django_capture_on_commit_callbacks,
):
    camp = CampFactory()
    booker = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    cancelling_participant = ParticipantFactory(
        camp=camp,
        first_name="Grace",
        last_name="Hopper",
    )
    PushSubscription.objects.create(
        participant=booker,
        endpoint="https://push.example.test/quick-cancel-booker",
        p256dh="key",
        auth="secret",
        categories=["booking_links"],
    )
    charge = Charge.objects.create(
        participant=cancelling_participant,
        kiosk_booked_by=booker,
        kind=Charge.Kind.DRINK,
        description="Wasser",
        quantity=1,
        unit_price=Decimal("1.50"),
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = cancelling_participant.pk
    session.save()

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 302
    message = PushMessage.objects.get()
    assert message.subscription.participant == booker
    assert message.body == "Grace Hopper hat Wasser für dich storniert."


@pytest.mark.django_db
def test_linked_participant_meal_retraction_passes_current_actor(
    client,
    django_capture_on_commit_callbacks,
):
    camp = CampFactory()
    booker = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    cancelling_participant = ParticipantFactory(
        camp=camp,
        first_name="Grace",
        last_name="Hopper",
    )
    PushSubscription.objects.create(
        participant=booker,
        endpoint="https://push.example.test/meal-cancel-booker",
        p256dh="key",
        auth="secret",
        categories=["booking_links"],
    )
    meal_date = timezone.localdate() + timedelta(days=2)
    charge = Charge.objects.create(
        participant=cancelling_participant,
        kiosk_booked_by=booker,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=1,
        unit_price=Decimal("8.00"),
        occurred_on=meal_date,
    )
    signup = MealSignup.objects.create(
        participant=cancelling_participant,
        meal_date=meal_date,
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        charge=charge,
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = cancelling_participant.pk
    session.save()

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("kiosk-home"),
            {"action": "meal_retract", "meal_signup_id": signup.pk},
        )

    assert response.status_code == 302
    message = PushMessage.objects.get()
    assert message.subscription.participant == booker
    assert message.body == "Grace Hopper hat Abendessen für dich storniert."


@pytest.mark.django_db
def test_expense_approval_queues_after_transaction_commit(django_capture_on_commit_callbacks):
    participant = ParticipantFactory()
    PushSubscription.objects.create(
        participant=participant,
        endpoint="https://push.example.test/expense-status",
        p256dh="key",
        auth="secret",
        categories=["expense_status"],
    )
    expense = Expense.objects.create(
        camp=participant.camp,
        participant=participant,
        category="Einkauf",
        description="Schrauben",
        amount=Decimal("12.50"),
        paid_on=date(2026, 7, 20),
        reimbursable=True,
        allocation_method=Expense.AllocationMethod.NONE,
    )

    with django_capture_on_commit_callbacks(execute=True):
        approve_shared_expense(expense, UserFactory())

    assert PushMessage.objects.filter(category="expense_status", subscription__participant=participant).exists()


@pytest.mark.django_db
def test_booking_invitation_view_queues_after_commit(client, django_capture_on_commit_callbacks):
    inviter = ParticipantFactory()
    invitee = ParticipantFactory(camp=inviter.camp)
    PushSubscription.objects.create(
        participant=invitee,
        endpoint="https://push.example.test/booking-invite",
        p256dh="key",
        auth="secret",
        categories=["booking_links"],
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = inviter.pk
    session[KIOSK_MODE_SESSION_KEY] = "private"
    session.save()

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("kiosk-home"),
            {"action": "booking_link_invite", "link-participant": invitee.pk},
        )

    assert response.status_code == 302
    assert PushMessage.objects.filter(category="booking_links", subscription__participant=invitee).exists()
