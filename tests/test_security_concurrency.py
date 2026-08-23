from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier, Event, Lock, local
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, close_old_connections, connection, connections, transaction
from django.db.models import QuerySet
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from billing import services as billing_services
from billing import views as billing_views
from billing.kiosk_access import KIOSK_ACCESS_COOKIE_NAME, KIOSK_PARTICIPANT_SESSION_KEY
from billing.models import (
    Camp,
    Charge,
    CreditPayout,
    FirstAdminBootstrapLock,
    MealBookingOverride,
    MealOrder,
    MealSignup,
    ParticipantFamilyMember,
    ParticipantFamilyMemberPin,
    ParticipantPin,
    PaymentAuditLog,
    PriceRule,
)
from billing.services import (
    calculate_participant_settlement,
    create_credit_payout,
    create_manual_charge,
    payment_audit_snapshot,
    restore_payment_from_audit_log,
)
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


def test_payment_restore_has_one_winner_across_postgresql_connections():
    _require_postgresql()
    admin = SuperUserFactory(username="payment-restore-race-admin")
    payment = PaymentFactory(amount=Decimal("42.50"), paid_on=date(2026, 7, 3), method="Überweisung", note="Original")
    payment.deleted_at = timezone.now()
    payment.deleted_by = admin
    payment.save(update_fields=["deleted_at", "deleted_by"])
    deletion_log = PaymentAuditLog.objects.create(
        participant=payment.participant,
        payment=payment,
        changed_by=admin,
        action=PaymentAuditLog.Action.DELETED,
        before=payment_audit_snapshot(payment),
        after={},
    )
    original_participant = payment.participant
    start_calls = Barrier(2)

    def restore_once() -> str:
        close_old_connections()
        try:
            stale_log = PaymentAuditLog.objects.select_related("payment").get(pk=deletion_log.pk)
            start_calls.wait(timeout=10)
            try:
                restore_payment_from_audit_log(stale_log, admin)
            except ValidationError:
                return "validation_error"
            return "restored"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(lambda _worker: restore_once(), (1, 2)))

    payment.refresh_from_db()
    assert results == ["restored", "validation_error"]
    assert payment.deleted_at is None
    assert payment.participant == original_participant
    assert payment.amount == Decimal("42.50")
    assert payment.paid_on.isoformat() == "2026-07-03"
    assert payment.method == "Überweisung"
    assert payment.note == "Original"
    assert PaymentAuditLog.objects.filter(action=PaymentAuditLog.Action.RESTORED).count() == 1
    assert calculate_participant_settlement(original_participant).total_paid == Decimal("42.50")


def test_quick_booking_replay_is_idempotent_across_postgresql_connections(kiosk_client, monkeypatch):
    _require_postgresql()
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)
    rule = PriceRuleFactory(camp=camp, kind=PriceRule.Kind.DRINK, name="Wasser")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    rendered_response = kiosk_client.get(reverse("kiosk-home"))
    token = rendered_response.context["quick_booking_token"]
    session_key = kiosk_client.session.session_key
    kiosk_access_cookie = kiosk_client.cookies[KIOSK_ACCESS_COOKIE_NAME].value
    authorization_lock_barrier = Barrier(2)
    real_lock_booking_authorization_dependencies = billing_views._lock_booking_authorization_dependencies

    def synchronize_before_authorization_lock(*args, **kwargs):
        authorization_lock_barrier.wait(timeout=10)
        return real_lock_booking_authorization_dependencies(*args, **kwargs)

    monkeypatch.setattr(
        billing_views,
        "_lock_booking_authorization_dependencies",
        synchronize_before_authorization_lock,
    )

    def submit_once() -> int:
        close_old_connections()
        client = Client()
        client.cookies[settings.SESSION_COOKIE_NAME] = session_key
        client.cookies[KIOSK_ACCESS_COOKIE_NAME] = kiosk_access_cookie
        try:
            return client.post(
                reverse("kiosk-home"),
                {
                    "action": "quick",
                    "quick-price_rule": rule.pk,
                    "quick-quantity": 1,
                    "quick-booking-token": token,
                },
            ).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(lambda _worker: submit_once(), (1, 2)))

    assert statuses == [302, 302]
    charge = Charge.objects.get(kiosk_confirmation_nonce__isnull=False)
    assert charge.participant == participant
    assert charge.kind == Charge.Kind.DRINK
    assert charge.quantity == Decimal("1")
    assert charge.unit_price == rule.unit_price


def test_credit_payout_same_key_different_participants_has_one_winner(monkeypatch):
    _require_postgresql()
    participant_a, _payout_a = _postgresql_credit_payout(Decimal("30.00"))
    participant_b, _payout_b = _postgresql_credit_payout(Decimal("30.00"))
    admin = SuperUserFactory(username="credit-payout-race-admin")
    key = uuid4()
    final_insert_barrier = Barrier(2)
    real_create = CreditPayout.objects.create

    def synchronize_final_insert(*args, **kwargs):
        final_insert_barrier.wait(timeout=10)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(CreditPayout.objects, "create", synchronize_final_insert)

    def submit_once(participant_id: int):
        close_old_connections()
        try:
            try:
                payout = create_credit_payout(
                    participant_id,
                    Decimal("30.00"),
                    CreditPayout.Method.CASH,
                    admin,
                    key,
                )
            except ValidationError as error:
                return "validation_error", str(error)
            except IntegrityError as error:
                return "integrity_error", str(error)
            return "created", payout.pk
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit_once, (participant_a.pk, participant_b.pk)))

    assert sorted(result[0] for result in results) == ["created", "validation_error"]
    assert all("anderen Zahlungskonto" in result[1] for result in results if result[0] == "validation_error")
    assert not any(result[0] == "integrity_error" for result in results)
    assert CreditPayout.objects.filter(idempotency_key=key).count() == 1


def test_manual_charge_revalidates_after_concurrent_camp_period_change(monkeypatch):
    _require_postgresql()
    camp = CampFactory(starts_on=date(2025, 7, 1), ends_on=date(2025, 7, 4))
    participant = ParticipantFactory(camp=camp)
    rule = PriceRuleFactory(camp=camp)
    camp_update_locked = Event()
    allow_camp_update_commit = Event()
    booking_reached_camp_lock = Event()
    booking_finished = Event()
    real_lock_manual_charge_camp = billing_services._lock_manual_charge_camp

    def signal_before_camp_lock(camp_id):
        booking_reached_camp_lock.set()
        return real_lock_manual_charge_camp(camp_id)

    monkeypatch.setattr(billing_services, "_lock_manual_charge_camp", signal_before_camp_lock)

    def create_booking():
        close_old_connections()
        try:
            try:
                create_manual_charge(
                    participant,
                    rule,
                    quantity=1,
                    description="Parallel",
                    occurred_on=date(2025, 7, 2),
                )
            except ValidationError as error:
                return "rejected", error.code
            return "created", None
        finally:
            booking_finished.set()
            connections.close_all()

    def update_camp_period():
        close_old_connections()
        try:
            with transaction.atomic():
                locked_camp = Camp.objects.select_for_update().get(pk=camp.pk)
                locked_camp.starts_on = date(2025, 7, 3)
                locked_camp.save(update_fields=["starts_on", "updated_at"])
                camp_update_locked.set()
                assert allow_camp_update_commit.wait(timeout=10)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        update_future = executor.submit(update_camp_period)
        assert camp_update_locked.wait(timeout=10)
        booking_future = executor.submit(create_booking)
        assert booking_reached_camp_lock.wait(timeout=10)
        assert not booking_finished.wait(timeout=0.5)
        allow_camp_update_commit.set()
        update_future.result(timeout=10)
        booking_result = booking_future.result(timeout=10)

    assert booking_result == ("rejected", "manual_charge_date_outside_camp")
    assert not Charge.objects.filter(participant=participant).exists()
    camp.refresh_from_db()
    assert camp.starts_on == date(2025, 7, 3)


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
