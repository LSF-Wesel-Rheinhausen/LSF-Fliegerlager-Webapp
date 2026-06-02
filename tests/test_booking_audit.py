from decimal import Decimal

import pytest
from django.urls import reverse

from billing.models import BookingAuditLog, Charge
from billing.permissions import EDITOR_GROUP
from tests.factories import ChargeFactory, GroupFactory, ParticipantFactory, SuperUserFactory, UserFactory


@pytest.mark.django_db
def test_admin_can_edit_booking_and_creates_audit_log(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    charge = ChargeFactory(
        kind=Charge.Kind.DRINK,
        description="Cola",
        quantity=Decimal("2.00"),
        unit_price=Decimal("2.50"),
        foerderfaehig=True,
    )
    client.force_login(admin)

    response = client.post(
        reverse("charge-edit", args=[charge.pk]),
        {
            "kind": Charge.Kind.DRINK,
            "description": "Cola korrigiert",
            "quantity": "3.00",
            "unit_price": "2.50",
            "foerderfaehig": "on",
            "occurred_on": "2026-07-01",
        },
    )

    charge.refresh_from_db()
    audit_log = BookingAuditLog.objects.get(charge=charge)
    assert response.status_code == 302
    assert response["Location"] == reverse("participant-detail", args=[charge.participant.pk])
    assert charge.description == "Cola korrigiert"
    assert charge.quantity == Decimal("3.00")
    assert charge.occurred_on.isoformat() == "2026-07-01"
    assert audit_log.changed_by == admin
    assert audit_log.before == {
        "kind": Charge.Kind.DRINK,
        "description": "Cola",
        "quantity": "2.00",
        "unit_price": "2.50",
        "foerderfaehig": True,
        "occurred_on": None,
    }
    assert audit_log.after == {
        "kind": Charge.Kind.DRINK,
        "description": "Cola korrigiert",
        "quantity": "3.00",
        "unit_price": "2.50",
        "foerderfaehig": True,
        "occurred_on": "2026-07-01",
    }


@pytest.mark.django_db
def test_editor_cannot_edit_booking_or_create_audit_log(client):
    editor = UserFactory(username="editor")
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    charge = ChargeFactory(description="Nicht editieren", quantity=Decimal("1.00"))
    client.force_login(editor)

    response = client.post(
        reverse("charge-edit", args=[charge.pk]),
        {
            "kind": Charge.Kind.OTHER,
            "description": "Manipuliert",
            "quantity": "9.00",
            "unit_price": "1.00",
        },
    )

    charge.refresh_from_db()
    assert response.status_code == 302
    assert reverse("login") in response["Location"]
    assert charge.description == "Nicht editieren"
    assert charge.quantity == Decimal("1.00")
    assert BookingAuditLog.objects.count() == 0


@pytest.mark.django_db
def test_participant_detail_renders_booking_audit_history_for_admin(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    charge = ChargeFactory(participant=participant, description="Abendessen", quantity=Decimal("1.00"))
    BookingAuditLog.objects.create(
        charge=charge,
        changed_by=admin,
        before={
            "kind": Charge.Kind.FOOD,
            "description": "Abendessen",
            "quantity": "1.00",
            "unit_price": "10.00",
            "foerderfaehig": True,
            "occurred_on": None,
        },
        after={
            "kind": Charge.Kind.FOOD,
            "description": "Abendessen korrigiert",
            "quantity": "2.00",
            "unit_price": "10.00",
            "foerderfaehig": True,
            "occurred_on": None,
        },
    )
    client.force_login(admin)

    response = client.get(reverse("participant-detail", args=[participant.pk]))

    assert response.status_code == 200
    assert b"Buchungen" in response.content
    assert b"Audit-Protokoll Buchungen" in response.content
    assert b"Abendessen korrigiert" in response.content
    assert reverse("charge-edit", args=[charge.pk]).encode() in response.content
