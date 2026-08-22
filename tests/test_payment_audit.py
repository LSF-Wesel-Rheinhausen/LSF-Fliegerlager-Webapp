from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

import billing.admin as billing_admin
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
    admin = billing_admin.PaymentAdmin(Payment, AdminSite())

    assert "payment_reference" in admin.list_display
    assert "deleted_at" in admin.readonly_fields
    assert "soft_delete_selected_payments" in admin.actions
    assert "restore_selected_payments" in admin.actions


@pytest.mark.django_db
def test_payment_audit_admin_reports_expected_validation_errors(monkeypatch):
    admin_user = SuperUserFactory(username="admin")
    payment = PaymentFactory()
    payment.deleted_at = timezone.now()
    payment.deleted_by = admin_user
    payment.save(update_fields=["deleted_at", "deleted_by"])
    audit_log = PaymentAuditLog.objects.create(
        participant=payment.participant,
        payment=payment,
        changed_by=admin_user,
        action=PaymentAuditLog.Action.DELETED,
        before={},
        after={},
    )
    request = RequestFactory().post("/admin/billing/paymentauditlog/")
    request.user = admin_user
    request._messages = MagicMock()
    admin = billing_admin.PaymentAuditLogAdmin(PaymentAuditLog, AdminSite())

    def raise_validation_error(_audit_log, _changed_by):
        raise ValidationError("already restored")

    monkeypatch.setattr(
        billing_admin,
        "restore_payment_from_audit_log",
        raise_validation_error,
    )

    admin.restore_payments_from_audit_log(request, PaymentAuditLog.objects.filter(pk=audit_log.pk))

    request._messages.add.assert_called_once()
    assert "0 Zahlung(en)" in request._messages.add.call_args.args[1]


@pytest.mark.django_db
def test_payment_audit_admin_propagates_unexpected_errors_and_rolls_back(monkeypatch):
    admin_user = SuperUserFactory(username="admin")
    participant = ParticipantFactory()
    payments = [PaymentFactory(participant=participant), PaymentFactory(participant=participant)]
    audit_logs = []
    for payment in payments:
        payment.deleted_at = timezone.now()
        payment.deleted_by = admin_user
        payment.save(update_fields=["deleted_at", "deleted_by"])
        audit_logs.append(
            PaymentAuditLog.objects.create(
                participant=payment.participant,
                payment=payment,
                changed_by=admin_user,
                action=PaymentAuditLog.Action.DELETED,
                before={},
                after={},
            )
        )
    request = RequestFactory().post("/admin/billing/paymentauditlog/")
    request.user = admin_user
    request._messages = MagicMock()
    admin = billing_admin.PaymentAuditLogAdmin(PaymentAuditLog, AdminSite())

    def restore_with_unexpected_failure(audit_log, changed_by):
        if audit_log.pk == audit_logs[0].pk:
            return restore_payment_from_audit_log(audit_log, changed_by)
        raise RuntimeError("database connection lost")

    monkeypatch.setattr(billing_admin, "restore_payment_from_audit_log", restore_with_unexpected_failure)

    with pytest.raises(RuntimeError, match="database connection lost"):
        admin.restore_payments_from_audit_log(
            request, PaymentAuditLog.objects.filter(pk__in=[log.pk for log in audit_logs]).order_by("pk")
        )

    assert list(
        Payment.objects.filter(pk__in=[payment.pk for payment in payments]).values_list("deleted_at", flat=True)
    ) == [
        payments[0].deleted_at,
        payments[1].deleted_at,
    ]
    assert not PaymentAuditLog.objects.filter(action=PaymentAuditLog.Action.RESTORED).exists()


@pytest.mark.django_db
def test_editor_cannot_execute_payment_admin_actions_or_mutate_payment_audit():
    editor = UserFactory(username="editor", is_staff=True)
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    payment = PaymentFactory()
    deleted_payment = PaymentFactory(participant=payment.participant)
    deleted_payment.deleted_at = timezone.now()
    deleted_payment.deleted_by = editor
    deleted_payment.save(update_fields=["deleted_at", "deleted_by"])
    audit_log = PaymentAuditLog.objects.create(
        participant=deleted_payment.participant,
        payment=deleted_payment,
        changed_by=editor,
        action=PaymentAuditLog.Action.DELETED,
        before={},
        after={},
    )
    request = RequestFactory().post("/admin/billing/payment/")
    request.user = editor
    request._messages = MagicMock()
    payment_admin = billing_admin.PaymentAdmin(Payment, AdminSite())
    audit_admin = billing_admin.PaymentAuditLogAdmin(PaymentAuditLog, AdminSite())

    with pytest.raises(PermissionDenied):
        payment_admin.soft_delete_selected_payments(request, Payment.objects.filter(pk=payment.pk))
    with pytest.raises(PermissionDenied):
        payment_admin.restore_selected_payments(request, Payment.objects.filter(pk=deleted_payment.pk))
    with pytest.raises(PermissionDenied):
        audit_admin.restore_payments_from_audit_log(request, PaymentAuditLog.objects.filter(pk=audit_log.pk))

    payment.refresh_from_db()
    deleted_payment.refresh_from_db()
    assert payment.deleted_at is None
    assert deleted_payment.deleted_at is not None
    assert PaymentAuditLog.objects.count() == 1

    assert audit_admin.has_add_permission(request) is False
    assert audit_admin.has_delete_permission(request) is False


@pytest.mark.django_db
def test_superuser_can_execute_payment_admin_action():
    admin_user = SuperUserFactory(username="admin")
    payment = PaymentFactory()
    request = RequestFactory().post("/admin/billing/payment/")
    request.user = admin_user
    request._messages = MagicMock()

    billing_admin.PaymentAdmin(Payment, AdminSite()).soft_delete_selected_payments(
        request, Payment.objects.filter(pk=payment.pk)
    )

    payment.refresh_from_db()
    assert payment.deleted_at is not None
    assert PaymentAuditLog.objects.filter(payment=payment, action=PaymentAuditLog.Action.DELETED).exists()


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
