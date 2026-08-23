from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, models, transaction
from django.urls import reverse

from billing.admin import CreditPayoutAdmin
from billing.forms import CreditPayoutForm
from billing.models import Charge, CreditPayout, Expense, Payment, Settlement
from billing.services import (
    calculate_available_credit,
    calculate_participant_settlement,
    create_credit_payout,
    create_settlement_run,
)
from tests.factories import (
    CampFactory,
    ChargeFactory,
    ExpenseFactory,
    ParticipantFactory,
    PaymentFactory,
    SuperUserFactory,
)


def _participant_with_credit():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    ChargeFactory(participant=participant, kind=Charge.Kind.OTHER, unit_price=Decimal("100.00"))
    PaymentFactory(participant=participant, amount=Decimal("150.00"), paid_on=date(2026, 1, 1))
    deleted_payment = PaymentFactory(participant=participant, amount=Decimal("25.00"), paid_on=date(2026, 1, 1))
    deleted_payment.deleted_at = deleted_payment.created_at
    deleted_payment.save(update_fields=["deleted_at"])
    ExpenseFactory(
        participant=participant,
        amount=Decimal("20.00"),
        reimbursable=True,
        status=Expense.Status.APPROVED,
    )
    return participant, camp


def _require_sqlite():
    if connection.vendor != "sqlite":
        pytest.skip("SQLite preserves values beyond DecimalField precision for constraint testing")


@pytest.mark.django_db
def test_available_credit_uses_current_settlement_and_active_payments_only():
    participant, _camp = _participant_with_credit()

    assert calculate_available_credit(participant) == Decimal("70.00")


@pytest.mark.django_db
def test_available_credit_excludes_soft_deleted_charges_in_single_settlement():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    active_charge = ChargeFactory(participant=participant, kind=Charge.Kind.OTHER, unit_price=Decimal("100.00"))
    deleted_charge = ChargeFactory(participant=participant, kind=Charge.Kind.OTHER, unit_price=Decimal("60.00"))
    deleted_charge.deleted_at = deleted_charge.created_at
    deleted_charge.save(update_fields=["deleted_at"])
    PaymentFactory(participant=participant, amount=Decimal("150.00"), paid_on=date(2026, 1, 1))

    assert calculate_available_credit(participant) == Decimal("50.00")
    settlement = calculate_participant_settlement(participant)
    prefetched_charges = settlement.participant._prefetched_objects_cache["charges"]
    assert [charge.pk for charge in prefetched_charges] == [active_charge.pk]


@pytest.mark.django_db
def test_full_and_partial_payouts_update_balance_without_negative_payment_records():
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()

    partial = create_credit_payout(
        participant, Decimal("30.00"), CreditPayout.Method.BANK_TRANSFER, admin_user, uuid4()
    )
    assert partial.amount == Decimal("30.00")
    assert calculate_available_credit(participant) == Decimal("40.00")

    full = create_credit_payout(participant, Decimal("40.00"), CreditPayout.Method.CASH, admin_user, uuid4())
    assert full.amount == Decimal("40.00")
    assert calculate_available_credit(participant) == Decimal("0.00")
    assert not Payment.objects.filter(participant=participant, amount__lt=0).exists()


@pytest.mark.django_db
def test_balance_includes_payouts_and_historical_settlement_snapshot_is_unchanged():
    participant, camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    run = create_settlement_run(camp, admin_user)
    snapshot = Settlement.objects.get(run=run, participant=participant)
    original_balance = snapshot.balance

    create_credit_payout(participant, Decimal("30.00"), CreditPayout.Method.BANK_TRANSFER, admin_user, uuid4())

    current = calculate_participant_settlement(participant)
    snapshot.refresh_from_db()
    assert current.balance == original_balance + Decimal("30.00")
    assert snapshot.balance == original_balance
    assert snapshot.data.get("total_payouts") is None


@pytest.mark.django_db
def test_credit_payout_endpoint_is_admin_only_post_only_and_mutates_only_on_success(client):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    editor = get_user_model().objects.create_user(username="editor", password="test")
    editor.groups.add(Group.objects.create(name="Bearbeiter"))
    url = reverse("credit-payout-create", args=[participant.pk])

    assert client.get(url).status_code == 302
    assert client.post(url, {"amount": "10.00", "method": "cash", "idempotency_key": str(uuid4())}).status_code == 302
    assert CreditPayout.objects.count() == 0

    client.force_login(editor)
    assert client.get(url).status_code == 302
    assert client.post(url, {"amount": "10.00", "method": "cash", "idempotency_key": str(uuid4())}).status_code == 302
    assert CreditPayout.objects.count() == 0

    client.force_login(admin_user)
    response = client.post(url, {"amount": "10.00", "method": "cash", "idempotency_key": str(uuid4())})
    assert response.status_code == 302
    assert CreditPayout.objects.count() == 1


@pytest.mark.django_db
def test_duplicate_idempotency_key_is_a_noop():
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    key = uuid4()

    first = create_credit_payout(participant, Decimal("30.00"), CreditPayout.Method.CASH, admin_user, key)
    duplicate = create_credit_payout(participant, Decimal("30.00"), CreditPayout.Method.CASH, admin_user, key)

    assert duplicate.pk == first.pk
    assert CreditPayout.objects.filter(participant=participant).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("changed_field", ["external_reference", "note"])
def test_replay_rejects_changed_payout_metadata(changed_field):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    key = uuid4()
    first_values = {"external_reference": "Ticket 42", "note": "Übergabe"}
    changed_values = {**first_values, changed_field: "Anderer Wert"}

    create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        **first_values,
    )

    with pytest.raises(ValidationError) as exc_info:
        create_credit_payout(
            participant,
            Decimal("30.00"),
            CreditPayout.Method.CASH,
            admin_user,
            key,
            **changed_values,
        )

    assert "anderen Auszahlungsdaten" in str(exc_info.value)
    assert "Anderer Wert" not in str(exc_info.value)
    assert CreditPayout.objects.count() == 1


@pytest.mark.django_db
def test_identical_payout_replay_compares_trimmed_metadata_without_second_write():
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    key = uuid4()

    first = create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        external_reference="  Ticket 42  ",
        note="\t Übergabe \n",
    )
    replay = create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        external_reference="Ticket 42",
        note="Übergabe",
    )

    assert replay.pk == first.pk
    assert first.external_reference == "Ticket 42"
    assert first.note == "Übergabe"
    assert CreditPayout.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [("external_reference", "x" * 121), ("note", "x" * 181)],
)
def test_payout_metadata_length_is_validated_before_idempotent_replay(field, value):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    key = uuid4()
    first = {"external_reference": "Ticket 42", "note": "Übergabe"}

    create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        **first,
    )

    with pytest.raises(ValidationError) as exc_info:
        create_credit_payout(
            participant,
            Decimal("30.00"),
            CreditPayout.Method.CASH,
            admin_user,
            key,
            **{**first, field: value},
        )

    assert "höchstens" in str(exc_info.value)
    assert CreditPayout.objects.count() == 1


@pytest.mark.django_db
def test_post_lock_replay_rejects_changed_payout_metadata(monkeypatch):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    key = uuid4()
    first = {"external_reference": "Ticket 42", "note": "Übergabe"}
    create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        **first,
    )

    real_filter = CreditPayout.objects.filter
    calls = 0

    def hide_first_lookup(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return CreditPayout.objects.none()
        return real_filter(*args, **kwargs)

    monkeypatch.setattr(CreditPayout.objects, "filter", hide_first_lookup)

    with pytest.raises(ValidationError) as exc_info:
        create_credit_payout(
            participant,
            Decimal("30.00"),
            CreditPayout.Method.CASH,
            admin_user,
            key,
            external_reference="Ticket 43",
            note=first["note"],
        )

    assert "anderen Auszahlungsdaten" in str(exc_info.value)
    assert CreditPayout.objects.count() == 1


@pytest.mark.django_db
def test_post_lock_identical_payout_replay_returns_existing_row(monkeypatch):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    key = uuid4()
    values = {"external_reference": "Ticket 42", "note": "Übergabe"}
    first = create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        **values,
    )

    real_filter = CreditPayout.objects.filter
    calls = 0

    def hide_first_lookup(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return CreditPayout.objects.none()
        return real_filter(*args, **kwargs)

    monkeypatch.setattr(CreditPayout.objects, "filter", hide_first_lookup)

    replay = create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        **values,
    )

    assert replay.pk == first.pk
    assert CreditPayout.objects.count() == 1


def _hide_initial_payout_lookups(monkeypatch):
    real_filter = CreditPayout.objects.filter
    calls = 0

    def hide_initial_lookups(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return CreditPayout.objects.none()
        return real_filter(*args, **kwargs)

    monkeypatch.setattr(CreditPayout.objects, "filter", hide_initial_lookups)


class _PostgresIntegrityCause(Exception):
    def __init__(self, constraint_name):
        super().__init__("duplicate key value violates unique constraint")
        self.diag = SimpleNamespace(constraint_name=constraint_name)


def _postgres_integrity_error(constraint_name):
    error = IntegrityError("duplicate key value violates unique constraint")
    error.__cause__ = _PostgresIntegrityCause(constraint_name)
    return error


def _credit_payout_idempotency_integrity_error():
    if connection.vendor == "postgresql":
        return _postgres_integrity_error("billing_creditpayout_idempotency_key_key")
    return IntegrityError("UNIQUE constraint failed: billing_creditpayout.idempotency_key")


@pytest.mark.django_db
def test_insert_integrity_error_revalidates_existing_payout_metadata(monkeypatch):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    key = uuid4()
    first = create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        external_reference="Ticket 42",
        note="Übergabe",
    )
    _hide_initial_payout_lookups(monkeypatch)

    def duplicate_insert(*args, **kwargs):
        raise _credit_payout_idempotency_integrity_error()

    monkeypatch.setattr(CreditPayout.objects, "create", duplicate_insert)

    with pytest.raises(ValidationError) as exc_info:
        create_credit_payout(
            participant,
            Decimal("30.00"),
            CreditPayout.Method.CASH,
            admin_user,
            key,
            external_reference="Ticket 43",
            note="Übergabe",
        )

    assert "anderen Auszahlungsdaten" in str(exc_info.value)
    assert first.pk == CreditPayout.objects.get(idempotency_key=key).pk


@pytest.mark.django_db
def test_insert_integrity_error_returns_identical_existing_payout(monkeypatch):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    key = uuid4()
    first = create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        external_reference="Ticket 42",
        note="Übergabe",
    )
    _hide_initial_payout_lookups(monkeypatch)

    def duplicate_insert(*args, **kwargs):
        raise _credit_payout_idempotency_integrity_error()

    monkeypatch.setattr(CreditPayout.objects, "create", duplicate_insert)

    replay = create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        external_reference="Ticket 42",
        note="Übergabe",
    )

    assert replay.pk == first.pk
    assert CreditPayout.objects.count() == 1


@pytest.mark.django_db
def test_insert_integrity_error_revalidates_postgresql_idempotency_constraint(monkeypatch):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    key = uuid4()
    first = create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        external_reference="Ticket 42",
        note="Übergabe",
    )
    _hide_initial_payout_lookups(monkeypatch)

    def duplicate_insert(*args, **kwargs):
        raise _postgres_integrity_error("billing_creditpayout_idempotency_key_key")

    monkeypatch.setattr(CreditPayout.objects, "create", duplicate_insert)

    replay = create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        external_reference="Ticket 42",
        note="Übergabe",
    )

    assert replay.pk == first.pk
    assert CreditPayout.objects.count() == 1


@pytest.mark.django_db
def test_insert_integrity_error_for_other_named_constraint_is_reraised(monkeypatch):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    key = uuid4()
    create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        external_reference="Ticket 42",
        note="Übergabe",
    )
    _hide_initial_payout_lookups(monkeypatch)

    def unrelated_insert(*args, **kwargs):
        raise _postgres_integrity_error("billing_creditpayout_other_unique")

    monkeypatch.setattr(CreditPayout.objects, "create", unrelated_insert)

    with pytest.raises(IntegrityError, match="duplicate key value"):
        create_credit_payout(
            participant,
            Decimal("30.00"),
            CreditPayout.Method.CASH,
            admin_user,
            key,
            external_reference="Ticket 42",
            note="Übergabe",
        )


@pytest.mark.django_db
def test_unknown_insert_integrity_error_is_not_treated_as_replay(monkeypatch):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    _hide_initial_payout_lookups(monkeypatch)

    def unrelated_integrity_error(*args, **kwargs):
        raise IntegrityError("UNIQUE constraint failed: billing_creditpayout.participant_id")

    monkeypatch.setattr(CreditPayout.objects, "create", unrelated_integrity_error)

    with pytest.raises(IntegrityError, match="participant_id"):
        create_credit_payout(
            participant,
            Decimal("30.00"),
            CreditPayout.Method.CASH,
            admin_user,
            uuid4(),
            external_reference="Ticket 42",
            note="Übergabe",
        )


@pytest.mark.django_db
def test_historical_payout_metadata_whitespace_is_semantically_canonicalized():
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    key = uuid4()
    first = create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        external_reference="Ticket 42",
        note="Übergabe",
    )
    CreditPayout.objects.filter(pk=first.pk).update(
        external_reference="  Ticket 42  ",
        note="\t Übergabe \n",
    )

    replay = create_credit_payout(
        participant,
        Decimal("30.00"),
        CreditPayout.Method.CASH,
        admin_user,
        key,
        external_reference="Ticket 42",
        note="Übergabe",
    )

    replay.refresh_from_db()
    assert replay.pk == first.pk
    assert replay.external_reference == "  Ticket 42  "
    assert replay.note == "\t Übergabe \n"
    assert CreditPayout.objects.count() == 1


@pytest.mark.django_db
def test_credit_payout_rejects_invalid_amount_and_sensitive_coordinates():
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()

    with pytest.raises(ValidationError):
        create_credit_payout(participant, Decimal("0.00"), CreditPayout.Method.CASH, admin_user, uuid4())
    with pytest.raises(ValidationError):
        create_credit_payout(
            participant,
            Decimal("10.00"),
            CreditPayout.Method.BANK_TRANSFER,
            admin_user,
            uuid4(),
            external_reference="DE89370400440532013000",
        )

    form = CreditPayoutForm(
        data={
            "amount": "10.00",
            "method": CreditPayout.Method.CASH,
            "idempotency_key": str(uuid4()),
            "note": "4111 1111 1111 1111",
        }
    )
    assert form.is_valid() is False
    assert "note" in form.errors


@pytest.mark.django_db
@pytest.mark.parametrize(
    "value",
    [
        "DE89 3704 0044 0532 0130 00",
        "4111-1111-1111-1111",
        "PayPal: payer@example.test",
        "paypal.me/payer",
        "+49 170 1234567",
        "0170 / 123 45 67",
    ],
)
def test_credit_payout_rejects_representative_payment_coordinates_at_model_boundary(value):
    payout = CreditPayout(
        participant=ParticipantFactory(),
        amount=Decimal("1.00"),
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
        note=value,
    )

    with pytest.raises(ValidationError):
        payout.full_clean()


@pytest.mark.parametrize(
    "value",
    [
        "DE89370400440532013000",
        "4111 1111 1111 1111",
        "PayPal-Konto: payer@example.test",
        "+49 (170) 123-45-67",
    ],
)
def test_credit_payout_form_rejects_representative_payment_coordinates(value):
    form = CreditPayoutForm(
        data={
            "amount": "10.00",
            "method": CreditPayout.Method.CASH,
            "idempotency_key": str(uuid4()),
            "external_reference": value,
        }
    )

    assert form.is_valid() is False
    assert "external_reference" in form.errors


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["paypal.me/payer", "+49 (170) 123-45-67"])
def test_credit_payout_service_rejects_payment_coordinates(value):
    participant, _camp = _participant_with_credit()

    with pytest.raises(ValidationError):
        create_credit_payout(
            participant,
            Decimal("10.00"),
            CreditPayout.Method.CASH,
            SuperUserFactory(),
            uuid4(),
            note=value,
        )


@pytest.mark.django_db
def test_credit_payout_model_rejects_standalone_email_address():
    payout = CreditPayout(
        participant=ParticipantFactory(),
        amount=Decimal("1.00"),
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
        external_reference="payer@example.test",
    )

    with pytest.raises(ValidationError):
        payout.full_clean()


def test_credit_payout_form_rejects_standalone_email_but_keeps_non_email_reference():
    form = CreditPayoutForm(
        data={
            "amount": "10.00",
            "method": CreditPayout.Method.CASH,
            "idempotency_key": str(uuid4()),
            "external_reference": "payer@example.test",
        }
    )
    safe_form = CreditPayoutForm(
        data={
            "amount": "10.00",
            "method": CreditPayout.Method.CASH,
            "idempotency_key": str(uuid4()),
            "external_reference": "Ticket ABC-123",
        }
    )

    assert form.is_valid() is False
    assert "external_reference" in form.errors
    assert safe_form.is_valid() is True


@pytest.mark.django_db
def test_credit_payout_service_rejects_standalone_email_address():
    participant, _camp = _participant_with_credit()

    with pytest.raises(ValidationError):
        create_credit_payout(
            participant,
            Decimal("10.00"),
            CreditPayout.Method.CASH,
            SuperUserFactory(),
            uuid4(),
            note="payer@example.test",
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "iban",
    ["DE89\u00a03704\u00a00044\u00a00532\u00a00130\u00a000", "DE89\u202f3704\u202f0044\u202f0532\u202f0130\u202f00"],
)
def test_credit_payout_model_rejects_unicode_whitespace_iban(iban):
    payout = CreditPayout(
        participant=ParticipantFactory(),
        amount=Decimal("1.00"),
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
        note=iban,
    )

    with pytest.raises(ValidationError):
        payout.full_clean()


@pytest.mark.parametrize(
    "iban",
    ["DE89\u00a03704\u00a00044\u00a00532\u00a00130\u00a000", "DE89\u202f3704\u202f0044\u202f0532\u202f0130\u202f00"],
)
def test_credit_payout_form_rejects_unicode_whitespace_iban(iban):
    form = CreditPayoutForm(
        data={
            "amount": "10.00",
            "method": CreditPayout.Method.CASH,
            "idempotency_key": str(uuid4()),
            "external_reference": iban,
        }
    )

    assert form.is_valid() is False
    assert "external_reference" in form.errors


@pytest.mark.django_db
@pytest.mark.parametrize(
    "iban",
    ["DE89\u00a03704\u00a00044\u00a00532\u00a00130\u00a000", "DE89\u202f3704\u202f0044\u202f0532\u202f0130\u202f00"],
)
def test_credit_payout_service_rejects_unicode_whitespace_iban(iban):
    participant, _camp = _participant_with_credit()

    with pytest.raises(ValidationError):
        create_credit_payout(
            participant,
            Decimal("10.00"),
            CreditPayout.Method.CASH,
            SuperUserFactory(),
            uuid4(),
            note=iban,
        )


def test_credit_payout_keeps_harmless_unicode_whitespace_text():
    form = CreditPayoutForm(
        data={
            "amount": "10.00",
            "method": CreditPayout.Method.CASH,
            "idempotency_key": str(uuid4()),
            "note": "Übergabe\u00a0vor\u202fOrt",
        }
    )

    assert form.is_valid() is True


@pytest.mark.django_db
def test_credit_payout_model_accepts_context_free_business_id():
    payout = CreditPayout(
        participant=ParticipantFactory(),
        amount=Decimal("1.00"),
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
        external_reference="Ticket 1234567890128",
    )

    payout.full_clean()


def test_credit_payout_form_accepts_context_free_business_id():
    form = CreditPayoutForm(
        data={
            "amount": "10.00",
            "method": CreditPayout.Method.CASH,
            "idempotency_key": str(uuid4()),
            "external_reference": "Ticket 1234567890128",
        }
    )

    assert form.is_valid() is True


@pytest.mark.django_db
def test_credit_payout_service_accepts_context_free_business_id():
    participant, _camp = _participant_with_credit()

    payout = create_credit_payout(
        participant,
        Decimal("10.00"),
        CreditPayout.Method.CASH,
        SuperUserFactory(),
        uuid4(),
        external_reference="Ticket 1234567890128",
    )

    assert payout.external_reference == "Ticket 1234567890128"


@pytest.mark.django_db
@pytest.mark.parametrize("card_number", ["4111 1111 1111 1111", "5555 5555 5555 4444"])
def test_credit_payout_model_rejects_visa_and_mastercard_test_numbers(card_number):
    payout = CreditPayout(
        participant=ParticipantFactory(),
        amount=Decimal("1.00"),
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
        note=card_number,
    )

    with pytest.raises(ValidationError):
        payout.full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize("card_number", ["4111 1111 1111 1111", "5555 5555 5555 4444"])
def test_credit_payout_service_rejects_visa_and_mastercard_test_numbers(card_number):
    participant, _camp = _participant_with_credit()

    with pytest.raises(ValidationError):
        create_credit_payout(
            participant,
            Decimal("10.00"),
            CreditPayout.Method.CASH,
            SuperUserFactory(),
            uuid4(),
            note=card_number,
        )


@pytest.mark.django_db
@pytest.mark.parametrize("text", ["Karte: 4111 1111 1111 1111", "Mastercard 5555 5555 5555 4444"])
def test_credit_payout_model_rejects_embedded_known_card_numbers(text):
    payout = CreditPayout(
        participant=ParticipantFactory(),
        amount=Decimal("1.00"),
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
        note=text,
    )

    with pytest.raises(ValidationError):
        payout.full_clean()


@pytest.mark.parametrize("text", ["Karte: 4111 1111 1111 1111", "Mastercard 5555 5555 5555 4444"])
def test_credit_payout_form_rejects_embedded_known_card_numbers(text):
    form = CreditPayoutForm(
        data={
            "amount": "10.00",
            "method": CreditPayout.Method.CASH,
            "idempotency_key": str(uuid4()),
            "note": text,
        }
    )

    assert form.is_valid() is False
    assert "note" in form.errors


@pytest.mark.django_db
@pytest.mark.parametrize("text", ["Karte: 4111 1111 1111 1111", "Mastercard 5555 5555 5555 4444"])
def test_credit_payout_service_rejects_embedded_known_card_numbers(text):
    participant, _camp = _participant_with_credit()

    with pytest.raises(ValidationError):
        create_credit_payout(
            participant,
            Decimal("10.00"),
            CreditPayout.Method.CASH,
            SuperUserFactory(),
            uuid4(),
            note=text,
        )


@pytest.mark.parametrize("value", ["REF-2026-001", "Ticket 123456", "Barzahlung vor Ort", ""])
def test_credit_payout_metadata_validation_keeps_harmless_values(value):
    form = CreditPayoutForm(
        data={
            "amount": "10.00",
            "method": CreditPayout.Method.CASH,
            "idempotency_key": str(uuid4()),
            "external_reference": value,
            "note": value,
        }
    )

    assert form.is_valid() is True


@pytest.mark.django_db
def test_editor_sees_payout_amount_and_method_but_not_historical_metadata(client):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    editor = get_user_model().objects.create_user(username="payout-editor", password="test")
    editor.groups.add(Group.objects.create(name="Bearbeiter"))
    payout = CreditPayout(
        participant=participant,
        amount=Decimal("10.00"),
        method=CreditPayout.Method.CASH,
        created_by=admin_user,
        idempotency_key=uuid4(),
        external_reference="DE89370400440532013000",
        note="PayPal: payer@example.test",
    )
    CreditPayout.objects.bulk_create([payout])

    client.force_login(editor)
    content = client.get(reverse("participant-detail", args=[participant.pk])).content.decode()

    assert "10,00 EUR" in content
    assert "Bar" in content
    assert payout.external_reference not in content
    assert payout.note not in content


@pytest.mark.django_db
def test_admin_sees_historical_payout_metadata_for_audit(client):
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    payout = CreditPayout(
        participant=participant,
        amount=Decimal("10.00"),
        method=CreditPayout.Method.CASH,
        created_by=admin_user,
        idempotency_key=uuid4(),
        external_reference="DE89370400440532013000",
        note="PayPal: payer@example.test",
    )
    CreditPayout.objects.bulk_create([payout])

    client.force_login(admin_user)
    content = client.get(reverse("participant-detail", args=[participant.pk])).content.decode()

    assert payout.external_reference in content
    assert payout.note in content


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_amount",
    [
        Decimal("-0.01"),
        Decimal("0.00"),
        Decimal("0.001"),
        Decimal("0.011"),
        Decimal("100000000.00"),
    ],
)
def test_credit_payout_full_clean_rejects_amounts_outside_decimal_field_contract(invalid_amount):
    payout = CreditPayout(
        participant=ParticipantFactory(),
        amount=invalid_amount,
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
    )

    with pytest.raises(ValidationError) as exc_info:
        payout.full_clean()

    assert "amount" in exc_info.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize("valid_amount", [Decimal("0.01"), Decimal("99999999.99")])
def test_credit_payout_full_clean_accepts_boundary_amounts(valid_amount):
    payout = CreditPayout(
        participant=ParticipantFactory(),
        amount=valid_amount,
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
    )

    payout.full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_amount",
    [
        Decimal("-0.01"),
        Decimal("0.00"),
        Decimal("0.001"),
        Decimal("0.011"),
        Decimal("100000000.00"),
    ],
)
def test_credit_payout_sqlite_database_rejects_amounts_outside_decimal_field_contract_on_bulk_create(invalid_amount):
    _require_sqlite()
    payout = CreditPayout(
        participant=ParticipantFactory(),
        amount=invalid_amount,
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        CreditPayout.objects.bulk_create([payout])

    assert CreditPayout.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_amount",
    [
        Decimal("-0.01"),
        Decimal("0.00"),
        Decimal("0.001"),
        Decimal("0.011"),
        Decimal("100000000.00"),
    ],
)
def test_credit_payout_sqlite_database_rejects_amounts_outside_decimal_field_contract_on_queryset_update(
    invalid_amount,
):
    _require_sqlite()
    payout = CreditPayout.objects.create(
        participant=ParticipantFactory(),
        amount=Decimal("1.00"),
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        CreditPayout.objects.filter(pk=payout.pk).update(amount=invalid_amount)

    payout.refresh_from_db()
    assert payout.amount == Decimal("1.00")


@pytest.mark.django_db
@pytest.mark.parametrize("valid_amount", [Decimal("0.01"), Decimal("99999999.99")])
def test_credit_payout_database_accepts_boundary_amounts(valid_amount):
    payout = CreditPayout(
        participant=ParticipantFactory(),
        amount=valid_amount,
        method=CreditPayout.Method.CASH,
        created_by=SuperUserFactory(),
        idempotency_key=uuid4(),
    )

    CreditPayout.objects.bulk_create([payout])

    assert CreditPayout.objects.get().amount == valid_amount


@pytest.mark.django_db
def test_credit_payout_is_append_only_and_admin_read_only():
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    payout = create_credit_payout(participant, Decimal("10.00"), CreditPayout.Method.CASH, admin_user, uuid4())

    payout.amount = Decimal("11.00")
    with pytest.raises(ValidationError):
        payout.save()
    with pytest.raises(ValidationError):
        payout.delete()

    model_admin = CreditPayoutAdmin(CreditPayout, admin.site)
    request = type("Request", (), {"user": admin_user})()
    assert model_admin.has_change_permission(request, payout) is False
    assert model_admin.has_delete_permission(request, payout) is False
    assert model_admin.actions == []


@pytest.mark.django_db
def test_participant_ui_and_settlement_export_distinguish_payouts(client):
    participant, camp = _participant_with_credit()
    admin_user = SuperUserFactory()
    create_credit_payout(participant, Decimal("10.00"), CreditPayout.Method.CASH, admin_user, uuid4())
    client.force_login(admin_user)

    response = client.get(reverse("participant-detail", args=[participant.pk]))
    content = response.content.decode()
    assert "Zahlungseingänge" in content
    assert "Auszahlungen" in content
    assert "Guthaben auszahlen" in content

    run = create_settlement_run(camp, admin_user)
    from billing.exporters import settlement_run_csv_bytes

    csv = settlement_run_csv_bytes(run).decode()
    assert "Ausgezahlt" in csv
    assert "10.00" in csv


@pytest.mark.django_db(transaction=True)
def test_concurrent_payouts_cannot_exceed_credit_on_postgresql():
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row-lock semantics")
    participant, _camp = _participant_with_credit()
    admin_user = SuperUserFactory()

    def payout(_: int):
        close_old_connections()
        try:
            return create_credit_payout(
                participant.pk,
                Decimal("50.00"),
                CreditPayout.Method.BANK_TRANSFER,
                admin_user,
                uuid4(),
            )
        except ValidationError:
            return None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(payout, range(2)))

    assert sum((result.amount for result in results if result is not None), Decimal("0.00")) <= Decimal("70.00")
    assert CreditPayout.objects.filter(participant_id=participant.pk).aggregate(total=models.Sum("amount"))[
        "total"
    ] <= Decimal("70.00")
