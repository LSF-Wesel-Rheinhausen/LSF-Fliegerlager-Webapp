from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from billing.admin import PaymentAdmin
from billing.models import Payment, PaymentAuditLog
from billing.permissions import EDITOR_GROUP
from billing.services import (
    calculate_camp_settlements,
    calculate_participant_settlement,
    restore_payment_from_audit_log,
)
from tests.factories import (
    GroupFactory,
    ParticipantFactory,
    PaymentFactory,
    SuperUserFactory,
    UserFactory,
)


@pytest.mark.django_db
def test_payment_reference_uses_human_readable_payment_id():
    payment = PaymentFactory()

    assert payment.payment_reference == f"Z#{payment.pk:05d}"


def test_payment_admin_exposes_soft_delete_actions():
    admin = PaymentAdmin(Payment, AdminSite())

    assert "payment_reference" in admin.list_display
    assert "deleted_at" in admin.readonly_fields
    assert "soft_delete_selected_payments" in admin.actions
    assert "restore_selected_payments" in admin.actions


@pytest.mark.django_db
def test_admin_soft_deletes_payment_and_records_audit_snapshot(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    payment = PaymentFactory(
        amount=Decimal("42.50"),
        method="Überweisung",
        note="Fehlbuchung",
    )
    participant = payment.participant
    client.force_login(admin)

    response = client.post(reverse("payment-delete", args=[payment.pk]))

    audit_log = PaymentAuditLog.objects.get()
    payment.refresh_from_db()
    assert response.status_code == 302
    assert response["Location"] == reverse("participant-detail", args=[participant.pk])
    assert Payment.objects.filter(pk=payment.pk).exists() is True
    assert payment.deleted_at is not None
    assert payment.deleted_by == admin
    assert audit_log.payment == payment
    assert audit_log.participant == participant
    assert audit_log.changed_by == admin
    assert audit_log.action == PaymentAuditLog.Action.DELETED
    assert audit_log.before == {
        "payment_reference": payment.payment_reference,
        "amount": "42.50",
        "paid_on": payment.paid_on.isoformat(),
        "method": "Überweisung",
        "note": "Fehlbuchung",
    }
    assert audit_log.after == {}


@pytest.mark.django_db
def test_editor_cannot_delete_payment_or_create_audit_log(client):
    editor = UserFactory(username="editor")
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    payment = PaymentFactory(note="Bleibt bestehen")
    client.force_login(editor)

    response = client.post(reverse("payment-delete", args=[payment.pk]))

    payment.refresh_from_db()
    assert response.status_code == 302
    assert reverse("login") in response["Location"]
    assert payment.deleted_at is None
    assert PaymentAuditLog.objects.count() == 0


@pytest.mark.django_db
def test_payment_delete_rejects_get_requests(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    payment = PaymentFactory()
    client.force_login(admin)

    response = client.get(reverse("payment-delete", args=[payment.pk]))

    payment.refresh_from_db()
    assert response.status_code == 405
    assert payment.deleted_at is None
    assert PaymentAuditLog.objects.count() == 0


@pytest.mark.django_db
def test_deleted_payment_is_hidden_from_participant_detail_and_settlement(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    PaymentFactory(participant=participant, amount=Decimal("10.00"), note="Bleibt aktiv")
    deleted = PaymentFactory(participant=participant, amount=Decimal("25.00"), note="Geloeschte Zahlung")
    deleted.deleted_at = timezone.now()
    deleted.deleted_by = admin
    deleted.save(update_fields=["deleted_at", "deleted_by"])
    client.force_login(admin)

    response = client.get(reverse("participant-detail", args=[participant.pk]))
    settlement = calculate_participant_settlement(participant)

    assert response.status_code == 200
    assert b"Geloeschte Zahlung" not in response.content
    assert b"Bleibt aktiv" in response.content
    assert settlement.total_paid == Decimal("10.00")


@pytest.mark.django_db
def test_deleted_payment_is_excluded_from_bulk_camp_settlements():
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory()
    PaymentFactory(participant=participant, amount=Decimal("10.00"))
    deleted = PaymentFactory(participant=participant, amount=Decimal("25.00"))
    deleted.deleted_at = timezone.now()
    deleted.deleted_by = admin
    deleted.save(update_fields=["deleted_at", "deleted_by"])

    settlements = calculate_camp_settlements(participant.camp)

    assert [result.total_paid for result in settlements] == [Decimal("10.00")]


@pytest.mark.django_db
def test_deleted_payment_cannot_be_deleted_again(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    payment = PaymentFactory()
    payment.deleted_at = timezone.now()
    payment.deleted_by = admin
    payment.save(update_fields=["deleted_at", "deleted_by"])
    client.force_login(admin)

    response = client.post(reverse("payment-delete", args=[payment.pk]))

    assert response.status_code == 404
    assert PaymentAuditLog.objects.count() == 0


@pytest.mark.django_db
def test_admin_restores_deleted_payment_from_audit_log(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    payment = PaymentFactory(amount=Decimal("42.50"))
    participant = payment.participant
    client.force_login(admin)
    client.post(reverse("payment-delete", args=[payment.pk]))
    deletion_log = PaymentAuditLog.objects.get(action=PaymentAuditLog.Action.DELETED)

    response = client.post(reverse("payment-audit-restore", args=[deletion_log.pk]))

    payment.refresh_from_db()
    restore_log = PaymentAuditLog.objects.get(action=PaymentAuditLog.Action.RESTORED)
    assert response.status_code == 302
    assert response["Location"] == reverse("participant-detail", args=[participant.pk])
    assert payment.deleted_at is None
    assert payment.deleted_by is None
    assert restore_log.payment == payment
    assert restore_log.changed_by == admin
    assert calculate_participant_settlement(participant).total_paid == Decimal("42.50")


@pytest.mark.django_db
def test_editor_cannot_restore_deleted_payment(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    payment = PaymentFactory()
    client.force_login(admin)
    client.post(reverse("payment-delete", args=[payment.pk]))
    deletion_log = PaymentAuditLog.objects.get(action=PaymentAuditLog.Action.DELETED)

    editor = UserFactory(username="editor")
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    client.force_login(editor)
    response = client.post(reverse("payment-audit-restore", args=[deletion_log.pk]))

    payment.refresh_from_db()
    assert response.status_code == 302
    assert reverse("login") in response["Location"]
    assert payment.deleted_at is not None


@pytest.mark.django_db
def test_restoring_an_already_restored_payment_is_rejected():
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    payment = PaymentFactory()
    audit_log = PaymentAuditLog.objects.create(
        participant=payment.participant,
        payment=payment,
        changed_by=admin,
        action=PaymentAuditLog.Action.DELETED,
        before={},
        after={},
    )

    with pytest.raises(ValidationError):
        restore_payment_from_audit_log(audit_log, admin)


@pytest.mark.django_db
def test_restore_rejects_non_deletion_audit_entries():
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    payment = PaymentFactory()
    audit_log = PaymentAuditLog.objects.create(
        participant=payment.participant,
        payment=payment,
        changed_by=admin,
        action=PaymentAuditLog.Action.RESTORED,
        before={},
        after={},
    )

    with pytest.raises(ValidationError):
        restore_payment_from_audit_log(audit_log, admin)
