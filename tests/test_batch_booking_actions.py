from unittest.mock import MagicMock

import pytest
from django.contrib.admin import AdminSite
from django.urls import reverse
from django.utils import timezone

from billing.admin import BookingAuditLogAdmin, ChargeAdmin
from billing.models import BookingAuditLog, Charge
from billing.permissions import EDITOR_GROUP
from tests.factories import ChargeFactory, GroupFactory, ParticipantFactory, SuperUserFactory, UserFactory


def _create_user(role="admin"):
    if role == "admin":
        return SuperUserFactory()
    user = UserFactory()
    user.groups.add(GroupFactory(name=EDITOR_GROUP))
    return user


@pytest.mark.django_db
def test_charge_batch_delete_view(client):
    admin_user = _create_user(role="admin")
    editor_user = _create_user(role="editor")
    participant = ParticipantFactory()

    charge1 = ChargeFactory(participant=participant, description="Buchung 1")
    charge2 = ChargeFactory(participant=participant, description="Buchung 2")
    charge3 = ChargeFactory(participant=participant, description="Unverändert")

    url = reverse("charge-batch-delete", kwargs={"participant_id": participant.pk})

    # Editor user should be rejected
    client.force_login(editor_user)
    response = client.post(url, {"selected_charges": [charge1.pk, charge2.pk]})
    assert response.status_code == 302
    assert Charge.objects.filter(deleted_at__isnull=True).count() == 3

    # Admin user should succeed
    client.force_login(admin_user)
    response = client.post(url, {"selected_charges": [charge1.pk, charge2.pk]})
    assert response.status_code == 302
    assert response.url == reverse("participant-detail", kwargs={"participant_id": participant.pk})

    charge1.refresh_from_db()
    charge2.refresh_from_db()
    charge3.refresh_from_db()

    assert charge1.deleted_at is not None
    assert charge1.deleted_by == admin_user
    assert charge2.deleted_at is not None
    assert charge2.deleted_by == admin_user
    assert charge3.deleted_at is None

    # Verify audit logs created
    audit_logs = BookingAuditLog.objects.filter(participant=participant, action=BookingAuditLog.Action.DELETED)
    assert audit_logs.count() == 2


@pytest.mark.django_db
def test_booking_audit_batch_restore_view(client):
    admin_user = _create_user(role="admin")
    editor_user = _create_user(role="editor")
    participant = ParticipantFactory()

    charge1 = ChargeFactory(participant=participant, description="Buchung 1", deleted_at=timezone.now())
    charge2 = ChargeFactory(participant=participant, description="Buchung 2", deleted_at=timezone.now())

    log1 = BookingAuditLog.objects.create(
        participant=participant,
        charge=charge1,
        changed_by=admin_user,
        action=BookingAuditLog.Action.DELETED,
        before={
            "description": "Buchung 1",
            "kind": "sonstiges",
            "quantity": "1.00",
            "unit_price": "5.00",
            "foerdersatz": "0.00",
        },
        after={},
    )
    log2 = BookingAuditLog.objects.create(
        participant=participant,
        charge=charge2,
        changed_by=admin_user,
        action=BookingAuditLog.Action.DELETED,
        before={
            "description": "Buchung 2",
            "kind": "sonstiges",
            "quantity": "1.00",
            "unit_price": "5.00",
            "foerdersatz": "0.00",
        },
        after={},
    )

    url = reverse("booking-audit-batch-restore", kwargs={"participant_id": participant.pk})

    # Editor should be rejected
    client.force_login(editor_user)
    response = client.post(url, {"selected_audit_logs": [log1.pk, log2.pk]})
    assert response.status_code == 302
    assert Charge.objects.filter(deleted_at__isnull=False).count() == 2

    # Admin should succeed
    client.force_login(admin_user)
    response = client.post(url, {"selected_audit_logs": [log1.pk, log2.pk]})
    assert response.status_code == 302
    assert response.url == reverse("participant-detail", kwargs={"participant_id": participant.pk})

    charge1.refresh_from_db()
    charge2.refresh_from_db()

    assert charge1.deleted_at is None
    assert charge2.deleted_at is None


@pytest.mark.django_db
def test_django_admin_charge_batch_actions(rf):
    admin_user = _create_user(role="admin")
    participant = ParticipantFactory()

    charge1 = ChargeFactory(participant=participant, description="Pos A")
    charge2 = ChargeFactory(participant=participant, description="Pos B")

    site = AdminSite()
    charge_admin = ChargeAdmin(Charge, site)

    request = rf.post("/")
    request.user = admin_user
    request._messages = MagicMock()

    # Soft delete action
    queryset = Charge.objects.filter(pk__in=[charge1.pk, charge2.pk])
    charge_admin.soft_delete_selected_charges(request, queryset)

    charge1.refresh_from_db()
    charge2.refresh_from_db()
    assert charge1.deleted_at is not None
    assert charge2.deleted_at is not None

    # Restore action
    charge_admin.restore_selected_charges(request, queryset)
    charge1.refresh_from_db()
    charge2.refresh_from_db()
    assert charge1.deleted_at is None
    assert charge2.deleted_at is None


@pytest.mark.django_db
def test_django_admin_booking_audit_log_batch_restore(rf):
    admin_user = _create_user(role="admin")
    participant = ParticipantFactory()

    charge = ChargeFactory(participant=participant, description="Gelöscht", deleted_at=timezone.now())
    log = BookingAuditLog.objects.create(
        participant=participant,
        charge=charge,
        changed_by=admin_user,
        action=BookingAuditLog.Action.DELETED,
        before={
            "description": "Gelöscht",
            "kind": "sonstiges",
            "quantity": "1.00",
            "unit_price": "5.00",
            "foerdersatz": "0.00",
        },
        after={},
    )

    site = AdminSite()
    audit_admin = BookingAuditLogAdmin(BookingAuditLog, site)

    request = rf.post("/")
    request.user = admin_user
    request._messages = MagicMock()

    queryset = BookingAuditLog.objects.filter(pk=log.pk)
    audit_admin.restore_charges_from_audit_log(request, queryset)

    charge.refresh_from_db()
    assert charge.deleted_at is None
