from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Event, Lock, local
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.db import DataError, IntegrityError, close_old_connections, connection, connections, transaction
from django.db.models import QuerySet
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from billing.kiosk_access import KIOSK_PARTICIPANT_SESSION_KEY
from billing.models import (
    Charge,
    CreditPayout,
    FirstAdminBootstrapLock,
    MealBookingOverride,
    MealOrder,
    MealSignup,
    ParticipantFamilyMember,
    ParticipantFamilyMemberPin,
    ParticipantPin,
    PriceRule,
)
from billing.services import calculate_participant_settlement
from tests.factories import (
    CampFactory,
    ChargeFactory,
    ParticipantFactory,
    PaymentFactory,
    PriceRuleFactory,
    SuperUserFactory,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _require_postgresql() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Regression requires PostgreSQL database semantics")


def _postgresql_credit_payout(amount: Decimal):
    participant = ParticipantFactory()
    ChargeFactory(participant=participant, kind=Charge.Kind.OTHER, unit_price=Decimal("100.00"))
    PaymentFactory(participant=participant, amount=Decimal("150.00"))
    payout = CreditPayout(
        participant=participant,
        amount=amount,
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
    )
    return participant, payout


def test_credit_payout_postgresql_normalizes_three_decimal_cents_and_keeps_settlement_consistent():
    _require_postgresql()
    participant, payout = _postgresql_credit_payout(Decimal("0.011"))

    CreditPayout.objects.bulk_create([payout])

    stored_payout = CreditPayout.objects.get(idempotency_key=payout.idempotency_key)
    settlement = calculate_participant_settlement(participant)
    assert stored_payout.amount == Decimal("0.01")
    assert settlement.total_payouts == Decimal("0.01")
    assert settlement.balance == Decimal("-49.99")


@pytest.mark.parametrize("invalid_amount", [Decimal("0.001"), Decimal("0.00"), Decimal("-0.01")])
def test_credit_payout_postgresql_rejects_values_invalid_after_numeric_coercion(invalid_amount):
    _require_postgresql()
    _participant, payout = _postgresql_credit_payout(invalid_amount)

    with pytest.raises(IntegrityError), transaction.atomic():
        CreditPayout.objects.bulk_create([payout])

    assert not CreditPayout.objects.filter(idempotency_key=payout.idempotency_key).exists()


def test_credit_payout_postgresql_rejects_numeric_overflow():
    _require_postgresql()
    _participant, payout = _postgresql_credit_payout(Decimal("100000000.00"))

    with pytest.raises(DataError), transaction.atomic():
        CreditPayout.objects.bulk_create([payout])

    assert not CreditPayout.objects.filter(idempotency_key=payout.idempotency_key).exists()


def test_first_admin_bootstrap_allows_only_one_winner_across_postgresql_connections(monkeypatch):
    _require_postgresql()
    FirstAdminBootstrapLock.objects.all().delete()
    initial_check_barrier = Barrier(2)
    exists_calls = 0
    exists_lock = Lock()
    real_exists = User.objects.exists

    def synchronized_empty_check() -> bool:
        nonlocal exists_calls
        result = real_exists()
        with exists_lock:
            exists_calls += 1
            call_number = exists_calls
        if call_number <= 2 and not result:
            initial_check_barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(User.objects, "exists", synchronized_empty_check)

    def submit_setup(username: str) -> int:
        close_old_connections()
        try:
            return (
                Client()
                .post(
                    reverse("setup"),
                    {
                        "username": username,
                        "email": f"{username}@example.org",
                        "password1": "strong-test-pass-123",
                        "password2": "strong-test-pass-123",
                    },
                )
                .status_code
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(submit_setup, ("race-admin-a", "race-admin-b")))

    assert statuses == [200, 302]
    assert User.objects.count() == 1
    assert FirstAdminBootstrapLock.objects.filter(pk=1).exists()


@pytest.mark.parametrize("pin_kind", ["participant", "family_member"])
def test_pin_failure_counter_is_atomic_across_postgresql_connections(pin_kind):
    _require_postgresql()
    participant = ParticipantFactory()
    if pin_kind == "participant":
        pin = participant.pin
        pin.set_pin("2468")
        pin.save()
        pin_model = ParticipantPin
    else:
        family_member = ParticipantFamilyMember.objects.create(
            guardian=participant,
            first_name="Kind",
            last_name="Muster",
            role=ParticipantFamilyMember.Role.COMPANION,
        )
        pin, _created = ParticipantFamilyMemberPin.objects.get_or_create(family_member=family_member)
        pin.set_pin("2468")
        pin.save()
        pin_model = ParticipantFamilyMemberPin

    pin_id = pin.pk
    loaded_barrier = Barrier(2)

    def submit_wrong_pin() -> bool:
        close_old_connections()
        try:
            stale_pin = pin_model.objects.get(pk=pin_id)
            loaded_barrier.wait(timeout=10)
            return stale_pin.check_pin("9999")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: submit_wrong_pin(), range(2)))

    pin.refresh_from_db()
    assert results == [False, False]
    assert pin.failed_attempts == 2


def test_manual_close_committed_after_initial_read_blocks_concurrent_meal_booking(kiosk_client, monkeypatch):
    _require_postgresql()
    today = timezone.localdate()
    meal_date = today + timedelta(days=2)
    camp = CampFactory(starts_on=today, ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        unit_price=Decimal("7.00"),
    )
    manager = User.objects.create_superuser(username="meal-manager-booking", password="test-password")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    initial_state_read = Event()
    continue_booking = Event()
    state_lock = Lock()
    state_calls = 0
    from billing import views

    real_meal_booking_state = views.meal_booking_state

    def pause_after_initial_state_read(*args, **kwargs):
        nonlocal state_calls
        state = real_meal_booking_state(*args, **kwargs)
        with state_lock:
            state_calls += 1
            is_initial_read = state_calls == 1
        if is_initial_read:
            initial_state_read.set()
            assert continue_booking.wait(timeout=10)
        return state

    monkeypatch.setattr(views, "meal_booking_state", pause_after_initial_state_read)

    def submit_booking() -> int:
        close_old_connections()
        try:
            return kiosk_client.post(
                reverse("kiosk-home"),
                {
                    "action": "meal",
                    "meal-meal_dates": [meal_date.isoformat()],
                    "meal-meal": MealSignup.Meal.DINNER,
                    "meal-variant": MealSignup.Variant.NORMAL,
                    "meal-target": [f"participant-{participant.pk}"],
                    f"meal-variant-participant-{participant.pk}": MealSignup.Variant.NORMAL,
                },
            ).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        booking_future = executor.submit(submit_booking)
        assert initial_state_read.wait(timeout=10)
        manager_client = Client()
        manager_client.force_login(manager)
        try:
            response = manager_client.post(
                reverse("meal-booking-override", args=[camp.pk]),
                {
                    "meal_date": meal_date.isoformat(),
                    "meal": MealSignup.Meal.DINNER,
                    "state": MealBookingOverride.State.CLOSED,
                },
            )
        finally:
            continue_booking.set()
        booking_status = booking_future.result(timeout=10)

    assert response.status_code == 302
    assert booking_status == 302
    assert MealBookingOverride.objects.filter(
        camp=camp,
        meal_date=meal_date,
        meal=MealSignup.Meal.DINNER,
        state=MealBookingOverride.State.CLOSED,
    ).exists()
    assert not MealSignup.objects.filter(participant=participant, meal_date=meal_date).exists()
    assert not Charge.objects.filter(participant=participant, occurred_on=meal_date).exists()


def test_manual_close_committed_after_initial_read_blocks_concurrent_meal_retraction(kiosk_client, monkeypatch):
    _require_postgresql()
    today = timezone.localdate()
    meal_date = today + timedelta(days=2)
    camp = CampFactory(starts_on=today, ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=1,
        unit_price=Decimal("7.00"),
        occurred_on=meal_date,
    )
    signup = MealSignup.objects.create(
        participant=participant,
        meal_date=meal_date,
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        charge=charge,
    )
    manager = User.objects.create_superuser(username="meal-manager-retraction", password="test-password")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    initial_state_read = Event()
    continue_retraction = Event()
    from billing import services

    real_meal_booking_state = services.meal_booking_state

    def pause_after_initial_state_read(*args, **kwargs):
        state = real_meal_booking_state(*args, **kwargs)
        initial_state_read.set()
        assert continue_retraction.wait(timeout=10)
        return state

    monkeypatch.setattr(services, "meal_booking_state", pause_after_initial_state_read)

    def submit_retraction() -> int:
        close_old_connections()
        try:
            return kiosk_client.post(
                reverse("kiosk-home"),
                {"action": "meal_retract", "meal_signup_id": signup.pk},
            ).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        retraction_future = executor.submit(submit_retraction)
        assert initial_state_read.wait(timeout=10)
        manager_client = Client()
        manager_client.force_login(manager)
        try:
            response = manager_client.post(
                reverse("meal-booking-override", args=[camp.pk]),
                {
                    "meal_date": meal_date.isoformat(),
                    "meal": MealSignup.Meal.DINNER,
                    "state": MealBookingOverride.State.CLOSED,
                },
            )
        finally:
            continue_retraction.set()
        retraction_status = retraction_future.result(timeout=10)

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert response.status_code == 302
    assert retraction_status == 200
    assert signup.status == MealSignup.Status.ACTIVE
    assert charge.deleted_at is None


def test_order_sent_after_initial_read_blocks_concurrent_meal_booking(kiosk_client, monkeypatch):
    _require_postgresql()
    today = timezone.localdate()
    meal_date = today + timedelta(days=1)
    camp = CampFactory(starts_on=today, ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        unit_price=Decimal("7.00"),
    )
    manager = User.objects.create_superuser(username="meal-manager-order-booking", password="test-password")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    initial_state_read = Event()
    continue_booking = Event()
    state_lock = Lock()
    state_calls = 0
    from billing import views

    real_meal_booking_state = views.meal_booking_state

    def pause_after_initial_state_read(*args, **kwargs):
        nonlocal state_calls
        state = real_meal_booking_state(*args, **kwargs)
        with state_lock:
            state_calls += 1
            is_initial_read = state_calls == 1
        if is_initial_read:
            initial_state_read.set()
            assert continue_booking.wait(timeout=10)
        return state

    monkeypatch.setattr(views, "meal_booking_state", pause_after_initial_state_read)

    def submit_booking() -> int:
        close_old_connections()
        try:
            return kiosk_client.post(
                reverse("kiosk-home"),
                {
                    "action": "meal",
                    "meal-meal_dates": [meal_date.isoformat()],
                    "meal-meal": MealSignup.Meal.DINNER,
                    "meal-variant": MealSignup.Variant.NORMAL,
                    "meal-target": [f"participant-{participant.pk}"],
                    f"meal-variant-participant-{participant.pk}": MealSignup.Variant.NORMAL,
                },
            ).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        booking_future = executor.submit(submit_booking)
        assert initial_state_read.wait(timeout=10)
        manager_client = Client()
        manager_client.force_login(manager)
        try:
            response = manager_client.post(reverse("meal-order-mark-sent", args=[camp.pk]))
        finally:
            continue_booking.set()
        booking_status = booking_future.result(timeout=10)

    assert response.status_code == 302
    assert booking_status == 302
    assert MealOrder.objects.filter(camp=camp, meal_date=meal_date, is_sent=True).exists()
    assert not MealSignup.objects.filter(participant=participant, meal_date=meal_date).exists()
    assert not Charge.objects.filter(participant=participant, occurred_on=meal_date).exists()


def test_order_sent_after_initial_read_blocks_concurrent_meal_retraction(kiosk_client, monkeypatch):
    _require_postgresql()
    today = timezone.localdate()
    meal_date = today + timedelta(days=1)
    camp = CampFactory(starts_on=today, ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=1,
        unit_price=Decimal("7.00"),
        occurred_on=meal_date,
    )
    signup = MealSignup.objects.create(
        participant=participant,
        meal_date=meal_date,
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        charge=charge,
    )
    manager = User.objects.create_superuser(username="meal-manager-order-retraction", password="test-password")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    initial_state_read = Event()
    continue_retraction = Event()
    from billing import services

    real_meal_booking_state = services.meal_booking_state

    def pause_after_initial_state_read(*args, **kwargs):
        state = real_meal_booking_state(*args, **kwargs)
        initial_state_read.set()
        assert continue_retraction.wait(timeout=10)
        return state

    monkeypatch.setattr(services, "meal_booking_state", pause_after_initial_state_read)

    def submit_retraction() -> int:
        close_old_connections()
        try:
            return kiosk_client.post(
                reverse("kiosk-home"),
                {"action": "meal_retract", "meal_signup_id": signup.pk},
            ).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        retraction_future = executor.submit(submit_retraction)
        assert initial_state_read.wait(timeout=10)
        manager_client = Client()
        manager_client.force_login(manager)
        try:
            response = manager_client.post(reverse("meal-order-mark-sent", args=[camp.pk]))
        finally:
            continue_retraction.set()
        retraction_status = retraction_future.result(timeout=10)

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert response.status_code == 302
    assert retraction_status == 200
    assert MealOrder.objects.filter(camp=camp, meal_date=meal_date, is_sent=True).exists()
    assert signup.status == MealSignup.Status.ACTIVE
    assert charge.deleted_at is None


def test_marking_order_sent_waits_for_booking_camp_lock(kiosk_client, monkeypatch):
    _require_postgresql()
    today = timezone.localdate()
    meal_date = today + timedelta(days=1)
    camp = CampFactory(starts_on=today, ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        unit_price=Decimal("7.00"),
    )
    manager = User.objects.create_superuser(username="meal-manager-order-lock", password="test-password")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    booking_holds_camp_lock = Event()
    release_booking = Event()
    order_camp_lock_attempted = Event()
    request_context = local()
    from billing import views

    real_lock_kiosk_price_rules = views._lock_kiosk_price_rules
    real_fetch_all = QuerySet._fetch_all

    def pause_booking_after_authoritative_state_check(locked_camp):
        booking_holds_camp_lock.set()
        assert release_booking.wait(timeout=10)
        return real_lock_kiosk_price_rules(locked_camp)

    def observe_order_camp_lock(queryset):
        if (
            getattr(request_context, "is_order_request", False)
            and queryset._result_cache is None
            and queryset.query.select_for_update
            and queryset.model.__name__ == "Camp"
        ):
            order_camp_lock_attempted.set()
        real_fetch_all(queryset)

    monkeypatch.setattr(views, "_lock_kiosk_price_rules", pause_booking_after_authoritative_state_check)
    monkeypatch.setattr(QuerySet, "_fetch_all", observe_order_camp_lock)

    def submit_booking() -> int:
        close_old_connections()
        try:
            return kiosk_client.post(
                reverse("kiosk-home"),
                {
                    "action": "meal",
                    "meal-meal_dates": [meal_date.isoformat()],
                    "meal-meal": MealSignup.Meal.DINNER,
                    "meal-variant": MealSignup.Variant.NORMAL,
                    "meal-target": [f"participant-{participant.pk}"],
                    f"meal-variant-participant-{participant.pk}": MealSignup.Variant.NORMAL,
                },
            ).status_code
        finally:
            connections.close_all()

    def submit_order() -> int:
        close_old_connections()
        request_context.is_order_request = True
        manager_client = Client()
        manager_client.force_login(manager)
        try:
            return manager_client.post(reverse("meal-order-mark-sent", args=[camp.pk])).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        booking_future = executor.submit(submit_booking)
        assert booking_holds_camp_lock.wait(timeout=10)
        order_future = executor.submit(submit_order)
        try:
            assert order_camp_lock_attempted.wait(timeout=10)
            assert not order_future.done()
        finally:
            release_booking.set()
        assert booking_future.result(timeout=10) == 302
        assert order_future.result(timeout=10) == 302

    assert MealSignup.objects.filter(participant=participant, meal_date=meal_date).exists()
    assert MealOrder.objects.filter(camp=camp, meal_date=meal_date, is_sent=True).exists()
