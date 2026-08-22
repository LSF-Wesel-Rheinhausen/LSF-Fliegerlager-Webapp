from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, models
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
