import re
from decimal import Decimal

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.admin.sites import AdminSite
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from billing.admin import ChargeAdmin
from billing.models import BookingAuditLog, Charge, Participant, PriceRule
from billing.permissions import EDITOR_GROUP
from billing.services import calculate_participant_settlement, calculate_position_report, create_manual_charge
from tests.factories import (
    CampFactory,
    ChargeFactory,
    GroupFactory,
    ParticipantFactory,
    PriceRuleFactory,
    SuperUserFactory,
    UserFactory,
)


def assert_manual_charge_dialog_auto_opens(response):
    opening_tag = re.search(
        rb'<dialog\b(?=[^>]*\bid="manual-charge-dialog")(?=[^>]*\bdata-auto-open-dialog\b)[^>]*>',
        response.content,
        re.DOTALL,
    )
    assert opening_tag is not None
    assert b"manualChargeDialog?.showModal()" in response.content


@pytest.mark.django_db
def test_booking_reference_uses_human_readable_charge_id():
    charge = ChargeFactory()

    assert charge.booking_reference == f"B#{charge.pk:05d}"
    assert charge.booking_reference in str(charge)


def test_charge_admin_displays_booking_reference():
    admin = ChargeAdmin(Charge, AdminSite())

    assert "booking_reference" in admin.list_display
    assert "id" in admin.search_fields


def _charge_admin_change_payload(charge: Charge, **overrides):
    payload = {
        "participant": str(charge.participant_id),
        "family_member": str(charge.family_member_id or ""),
        "kind": charge.kind,
        "description": charge.description,
        "quantity": str(charge.quantity),
        "unit_price": str(charge.unit_price),
        "foerdersatz": str(charge.foerdersatz),
        "occurred_on": charge.occurred_on.isoformat() if charge.occurred_on else "",
        "kiosk_booked_by": str(charge.kiosk_booked_by_id or ""),
        "_save": "Speichern",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_django_admin_description_edit_clears_position_report_description(client):
    admin = SuperUserFactory(username="admin")
    charge = ChargeFactory(
        description="Wasser (Kiosk) für Historisches Ziel",
        position_report_description="Wasser (Kiosk)",
    )
    client.force_login(admin)

    response = client.post(
        reverse("admin:billing_charge_change", args=[charge.pk]),
        _charge_admin_change_payload(charge, description="Manuell korrigierter Ledgertext"),
    )

    charge.refresh_from_db()
    assert response.status_code == 302
    assert charge.description == "Manuell korrigierter Ledgertext"
    assert charge.position_report_description is None
    report = calculate_position_report(charge.participant.camp)
    assert [article.description for article in report.articles] == ["Manuell korrigierter Ledgertext"]
    assert LogEntry.objects.filter(object_id=str(charge.pk), user=admin).exists()


@pytest.mark.django_db
def test_django_admin_non_description_edit_preserves_position_report_description(client):
    admin = SuperUserFactory(username="admin")
    charge = ChargeFactory(
        description="Wasser (Kiosk) für Historisches Ziel",
        position_report_description="Wasser (Kiosk)",
        quantity=Decimal("1.00"),
    )
    client.force_login(admin)

    response = client.post(
        reverse("admin:billing_charge_change", args=[charge.pk]),
        _charge_admin_change_payload(charge, quantity="3.00"),
    )

    charge.refresh_from_db()
    assert response.status_code == 302
    assert charge.description == "Wasser (Kiosk) für Historisches Ziel"
    assert charge.quantity == Decimal("3.00")
    assert charge.position_report_description == "Wasser (Kiosk)"
    report = calculate_position_report(charge.participant.camp)
    assert [article.description for article in report.articles] == ["Wasser (Kiosk)"]
    assert LogEntry.objects.filter(object_id=str(charge.pk), user=admin).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("price_rule_kind", "expected_charge_kind"),
    [
        (PriceRule.Kind.CAMP_FLAT, Charge.Kind.CAMP_FLAT),
        (PriceRule.Kind.NIGHT, Charge.Kind.OTHER),
        (PriceRule.Kind.MEAL, Charge.Kind.FOOD),
        (PriceRule.Kind.DRINK, Charge.Kind.DRINK),
        (PriceRule.Kind.OTHER, Charge.Kind.OTHER),
    ],
)
def test_editor_can_add_manual_charge_from_price_rule(
    client,
    price_rule_kind,
    expected_charge_kind,
):
    editor = UserFactory(username="editor")
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    rule = PriceRuleFactory(
        camp=participant.camp,
        kind=price_rule_kind,
        name="Sonderpreis",
        unit_price=Decimal("4.25"),
        foerdersatz=Decimal("0.2500"),
    )
    client.force_login(editor)

    response = client.post(
        reverse("participant-detail", args=[participant.pk]),
        {
            "action": "add_manual_charge",
            "price_rule_id": str(rule.pk),
            "quantity": "3",
            "description": "Sonderleistung",
        },
    )

    charge = Charge.objects.get(participant=participant)
    response_messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert response.status_code == 302
    assert response["Location"] == reverse("participant-detail", args=[participant.pk])
    assert response_messages == ["Buchung 'Sonderpreis' hinzugefügt."]
    assert charge.kind == expected_charge_kind
    assert charge.description == "Sonderleistung"
    assert charge.quantity == Decimal("3.00")
    assert charge.unit_price == Decimal("4.25")
    assert charge.foerdersatz == Decimal("0.2500")
    assert charge.total == Decimal("12.75")
    assert BookingAuditLog.objects.count() == 0


@pytest.mark.django_db
def test_manual_charge_uses_price_rule_name_without_description(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory()
    rule = PriceRuleFactory(camp=participant.camp, name="Übernachtung extra")
    client.force_login(admin)

    response = client.post(
        reverse("participant-detail", args=[participant.pk]),
        {
            "action": "add_manual_charge",
            "price_rule_id": str(rule.pk),
            "quantity": "1",
            "description": "   ",
        },
    )

    assert response.status_code == 302
    assert Charge.objects.get(participant=participant).description == "Übernachtung extra"


@pytest.mark.django_db
def test_manual_charge_price_rule_label_uses_localized_grouping(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory()
    PriceRuleFactory(camp=participant.camp, name="Großpreis", unit_price=Decimal("1234.50"))
    client.force_login(admin)

    response = client.get(reverse("participant-detail", args=[participant.pk]))

    assert response.status_code == 200
    assert "Großpreis (1.234,50 €)" in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("quantity", [None, "abc", "0", "-1", "100"])
def test_manual_charge_rejects_invalid_quantity_without_writing(client, quantity):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory()
    rule = PriceRuleFactory(camp=participant.camp)
    payload = {
        "action": "add_manual_charge",
        "price_rule_id": str(rule.pk),
        "description": "Ungültig",
    }
    if quantity is not None:
        payload["quantity"] = quantity
    client.force_login(admin)

    response = client.post(reverse("participant-detail", args=[participant.pk]), payload)

    assert response.status_code == 200
    assert "quantity" in response.context["manual_charge_form"].errors
    assert_manual_charge_dialog_auto_opens(response)
    quantity_input = re.search(
        rb'<input\b(?=[^>]*\bid="id_quantity")(?=[^>]*\baria-invalid="true")'
        rb'(?=[^>]*\baria-describedby="id_quantity_error")[^>]*>',
        response.content,
        re.DOTALL,
    )
    quantity_error = re.search(
        rb'<span\b(?=[^>]*\bid="id_quantity_error")(?=[^>]*\brole="alert")[^>]*>',
        response.content,
        re.DOTALL,
    )
    assert quantity_input is not None
    assert quantity_error is not None
    assert Charge.objects.filter(participant=participant).exists() is False


@pytest.mark.django_db
@pytest.mark.parametrize("invalid_rule", ["missing", "malformed", "foreign", "archived", "invalid_kind"])
def test_manual_charge_rejects_unavailable_price_rule_without_writing(client, invalid_rule):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory()
    PriceRuleFactory(camp=participant.camp, name="Verfügbar")
    payload = {
        "action": "add_manual_charge",
        "quantity": "1",
        "description": "Ungültig",
    }
    if invalid_rule == "malformed":
        payload["price_rule_id"] = "not-an-id"
    elif invalid_rule == "foreign":
        foreign_camp = CampFactory(name="Fremdes Lager", year=2026)
        payload["price_rule_id"] = str(PriceRuleFactory(camp=foreign_camp, name="Fremdes Lager").pk)
    elif invalid_rule == "archived":
        payload["price_rule_id"] = str(PriceRuleFactory(camp=participant.camp, name="Archiviert", is_archived=True).pk)
    elif invalid_rule == "invalid_kind":
        payload["price_rule_id"] = str(PriceRuleFactory(camp=participant.camp, name="Ungültige Art", kind="invalid").pk)
    client.force_login(admin)

    response = client.post(reverse("participant-detail", args=[participant.pk]), payload)

    assert response.status_code == 200
    assert "price_rule_id" in response.context["manual_charge_form"].errors
    assert_manual_charge_dialog_auto_opens(response)
    assert b'aria-describedby="id_price_rule_id_error"' in response.content
    assert b'id="id_price_rule_id_error" class="helptext error" role="alert"' in response.content
    assert Charge.objects.filter(participant=participant).exists() is False


@pytest.mark.django_db
def test_manual_charge_rejects_too_long_description_without_writing(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory()
    rule = PriceRuleFactory(camp=participant.camp)
    client.force_login(admin)

    response = client.post(
        reverse("participant-detail", args=[participant.pk]),
        {
            "action": "add_manual_charge",
            "price_rule_id": str(rule.pk),
            "quantity": "1",
            "description": "x" * 181,
        },
    )

    assert response.status_code == 200
    assert "description" in response.context["manual_charge_form"].errors
    assert_manual_charge_dialog_auto_opens(response)
    assert Charge.objects.filter(participant=participant).exists() is False


@pytest.mark.django_db
def test_archived_participant_cannot_receive_manual_charge(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory(archived_at=timezone.now(), archived_by=admin)
    rule = PriceRuleFactory(camp=participant.camp)
    client.force_login(admin)

    detail_response = client.get(reverse("participant-detail", args=[participant.pk]))
    post_response = client.post(
        reverse("participant-detail", args=[participant.pk]),
        {
            "action": "add_manual_charge",
            "price_rule_id": str(rule.pk),
            "quantity": "1",
            "description": "Nicht erlaubt",
        },
    )

    assert detail_response.status_code == 200
    assert b"Buchung hinzuf\xc3\xbcgen" not in detail_response.content
    assert b"manual-charge-dialog" not in detail_response.content
    assert post_response.status_code == 404
    assert Charge.objects.filter(participant=participant).exists() is False


@pytest.mark.django_db
def test_create_manual_charge_uses_fresh_locked_price_rule_values():
    participant = ParticipantFactory()
    rule = PriceRuleFactory(
        camp=participant.camp,
        name="Alter Preis",
        unit_price=Decimal("2.50"),
        foerdersatz=Decimal("0.1000"),
    )
    PriceRule.objects.filter(pk=rule.pk).update(
        name="Aktueller Preis",
        unit_price=Decimal("3.75"),
        foerdersatz=Decimal("0.2000"),
    )

    charge = create_manual_charge(participant, rule, quantity=2, description="")

    assert charge.description == "Aktueller Preis"
    assert charge.unit_price == Decimal("3.75")
    assert charge.foerdersatz == Decimal("0.2000")


@pytest.mark.django_db
def test_create_manual_charge_rejects_freshly_archived_participant():
    participant = ParticipantFactory()
    rule = PriceRuleFactory(camp=participant.camp)
    Participant.objects.filter(pk=participant.pk).update(archived_at=timezone.now())

    with pytest.raises(ValidationError, match="archivierte Teilnehmer") as error_info:
        create_manual_charge(participant, rule, quantity=1, description="")

    assert error_info.value.code == "manual_charge_participant_archived"
    assert Charge.objects.filter(participant=participant).exists() is False


@pytest.mark.django_db
def test_admin_can_edit_booking_and_creates_audit_log(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    charge = ChargeFactory(
        kind=Charge.Kind.DRINK,
        description="Cola",
        position_report_description="Cola (Kiosk)",
        quantity=Decimal("2.00"),
        unit_price=Decimal("2.50"),
        foerdersatz=Decimal("0.5000"),
    )
    client.force_login(admin)

    response = client.post(
        reverse("charge-edit", args=[charge.pk]),
        {
            "kind": Charge.Kind.DRINK,
            "description": "Cola korrigiert",
            "quantity": "3.00",
            "unit_price": "2.50",
            "foerdersatz": "50",
            "occurred_on": "2026-07-01",
        },
    )

    charge.refresh_from_db()
    audit_log = BookingAuditLog.objects.get(charge=charge)
    assert response.status_code == 302
    assert response["Location"] == reverse("participant-detail", args=[charge.participant.pk])
    assert charge.description == "Cola korrigiert"
    assert charge.position_report_description is None
    assert charge.quantity == Decimal("3.00")
    assert charge.occurred_on.isoformat() == "2026-07-01"
    assert audit_log.changed_by == admin
    assert audit_log.before == {
        "booking_reference": charge.booking_reference,
        "kind": Charge.Kind.DRINK,
        "description": "Cola",
        "quantity": "2.00",
        "unit_price": "2.50",
        "foerdersatz": "0.5000",
        "occurred_on": None,
    }
    assert audit_log.after == {
        "booking_reference": charge.booking_reference,
        "kind": Charge.Kind.DRINK,
        "description": "Cola korrigiert",
        "quantity": "3.00",
        "unit_price": "2.50",
        "foerdersatz": "0.5000",
        "occurred_on": "2026-07-01",
    }
    report = calculate_position_report(charge.participant.camp)
    assert [article.description for article in report.articles] == ["Cola korrigiert"]


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
def test_admin_can_delete_booking_and_keeps_audit_log(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    charge = ChargeFactory(
        kind=Charge.Kind.OTHER,
        description="Fehlbuchung",
        quantity=Decimal("1.00"),
        unit_price=Decimal("9.50"),
        foerdersatz=Decimal("0"),
    )
    participant = charge.participant
    client.force_login(admin)

    response = client.post(reverse("charge-delete", args=[charge.pk]))

    audit_log = BookingAuditLog.objects.get()
    charge.refresh_from_db()
    assert response.status_code == 302
    assert response["Location"] == reverse("participant-detail", args=[participant.pk])
    assert Charge.objects.filter(pk=charge.pk).exists() is True
    assert charge.deleted_at is not None
    assert charge.deleted_by == admin
    assert audit_log.charge == charge
    assert audit_log.participant == participant
    assert audit_log.changed_by == admin
    assert audit_log.action == BookingAuditLog.Action.DELETED
    assert audit_log.before == {
        "booking_reference": charge.booking_reference,
        "kind": Charge.Kind.OTHER,
        "description": "Fehlbuchung",
        "quantity": "1.00",
        "unit_price": "9.50",
        "foerdersatz": "0.0000",
        "occurred_on": None,
    }
    assert audit_log.after == {}


@pytest.mark.django_db
def test_editor_cannot_delete_booking_or_create_audit_log(client):
    editor = UserFactory(username="editor")
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    charge = ChargeFactory(description="Bleibt bestehen", quantity=Decimal("1.00"))
    client.force_login(editor)

    response = client.post(reverse("charge-delete", args=[charge.pk]))

    assert response.status_code == 302
    assert reverse("login") in response["Location"]
    assert Charge.objects.filter(pk=charge.pk).exists() is True
    assert BookingAuditLog.objects.count() == 0


@pytest.mark.django_db
def test_deleted_booking_is_hidden_from_participant_detail_and_settlement(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    charge = ChargeFactory(participant=participant, description="Gelöschte Kosten", unit_price=Decimal("9.50"))
    charge.deleted_at = timezone.now()
    charge.deleted_by = admin
    charge.save(update_fields=["deleted_at", "deleted_by"])
    client.force_login(admin)

    response = client.get(reverse("participant-detail", args=[participant.pk]))
    settlement = calculate_participant_settlement(participant)

    assert response.status_code == 200
    assert b"Gel\xc3\xb6schte Kosten" not in response.content
    assert charge.booking_reference.encode() not in response.content
    assert settlement.total_due == Decimal("0.00")


@pytest.mark.django_db
def test_deleted_booking_cannot_be_edited_or_deleted_again(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    charge = ChargeFactory(description="Gelöschte Kosten")
    charge.deleted_at = timezone.now()
    charge.deleted_by = admin
    charge.save(update_fields=["deleted_at", "deleted_by"])
    client.force_login(admin)

    edit_response = client.get(reverse("charge-edit", args=[charge.pk]))
    delete_response = client.post(reverse("charge-delete", args=[charge.pk]))

    assert edit_response.status_code == 404
    assert delete_response.status_code == 404
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
            "foerdersatz": "0.5000",
            "occurred_on": None,
        },
        after={
            "kind": Charge.Kind.FOOD,
            "description": "Abendessen korrigiert",
            "quantity": "2.00",
            "unit_price": "10.00",
            "foerdersatz": "0.5000",
            "occurred_on": None,
        },
    )
    client.force_login(admin)

    response = client.get(reverse("participant-detail", args=[participant.pk]))

    assert response.status_code == 200
    assert b"Buchungen" in response.content
    assert b"\xc3\x84nderungsprotokoll" in response.content
    assert charge.booking_reference.encode() in response.content
    assert b"Abendessen korrigiert" in response.content
    assert reverse("charge-edit", args=[charge.pk]).encode() in response.content
    assert reverse("charge-delete", args=[charge.pk]).encode() in response.content
    assert response.content.count(b'class="responsive-record-table"') >= 2
    assert b'data-label="Beschreibung"' in response.content
    assert b'data-label="Vorher"' in response.content
    assert b'data-label="Nachher"' in response.content


@pytest.mark.django_db
def test_participant_detail_renders_deleted_booking_audit_history(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    charge = ChargeFactory(participant=participant, description="Doppelte Buchung")
    charge.deleted_at = timezone.now()
    charge.deleted_by = admin
    charge.save(update_fields=["deleted_at", "deleted_by"])
    BookingAuditLog.objects.create(
        participant=participant,
        charge=charge,
        changed_by=admin,
        action=BookingAuditLog.Action.DELETED,
        before={
            "kind": Charge.Kind.OTHER,
            "description": "Doppelte Buchung",
            "quantity": "1.00",
            "unit_price": "4.00",
            "foerdersatz": "0.0000",
            "occurred_on": None,
        },
        after={},
    )
    client.force_login(admin)

    response = client.get(reverse("participant-detail", args=[participant.pk]))

    assert response.status_code == 200
    assert b"Doppelte Buchung" in response.content
    assert b"Gel\xc3\xb6scht" in response.content
    assert reverse("booking-audit-restore", args=[BookingAuditLog.objects.get().pk]).encode() in response.content


@pytest.mark.django_db
def test_admin_can_restore_deleted_booking_from_audit_log(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    deleted_charge = ChargeFactory(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Frühstück",
        quantity=Decimal("2.00"),
        unit_price=Decimal("4.50"),
        foerdersatz=Decimal("0.5000"),
        occurred_on="2026-07-02",
    )
    deleted_charge.deleted_at = timezone.now()
    deleted_charge.deleted_by = admin
    deleted_charge.save(update_fields=["deleted_at", "deleted_by"])
    deleted_log = BookingAuditLog.objects.create(
        participant=participant,
        charge=deleted_charge,
        changed_by=admin,
        action=BookingAuditLog.Action.DELETED,
        before={
            "booking_reference": deleted_charge.booking_reference,
            "kind": Charge.Kind.FOOD,
            "description": "Frühstück",
            "quantity": "2.00",
            "unit_price": "4.50",
            "foerdersatz": "0.5000",
            "occurred_on": "2026-07-02",
        },
        after={},
    )
    client.force_login(admin)

    response = client.post(reverse("booking-audit-restore", args=[deleted_log.pk]), follow=True)

    restored_charge = Charge.objects.get(pk=deleted_charge.pk)
    deleted_log.refresh_from_db()
    restored_log = BookingAuditLog.objects.exclude(pk=deleted_log.pk).get()
    assert response.status_code == 200
    assert response.redirect_chain == [(reverse("participant-detail", args=[participant.pk]), 302)]
    assert b"Fr\xc3\xbchst\xc3\xbcck" in response.content
    assert b"Wiederhergestellt" in response.content
    assert restored_charge.pk == deleted_charge.pk
    assert restored_charge.booking_reference == deleted_charge.booking_reference
    assert restored_charge.deleted_at is None
    assert restored_charge.deleted_by is None
    assert restored_charge.kind == Charge.Kind.FOOD
    assert restored_charge.description == "Frühstück"
    assert restored_charge.quantity == Decimal("2.00")
    assert restored_charge.unit_price == Decimal("4.50")
    assert restored_charge.foerdersatz == Decimal("0.5000")
    assert restored_charge.occurred_on.isoformat() == "2026-07-02"
    assert deleted_log.charge == restored_charge
    assert restored_log.participant == participant
    assert restored_log.charge == restored_charge
    assert restored_log.changed_by == admin
    assert restored_log.action == BookingAuditLog.Action.RESTORED
    assert restored_log.before == {
        "booking_reference": restored_charge.booking_reference,
        "kind": Charge.Kind.FOOD,
        "description": "Frühstück",
        "quantity": "2.00",
        "unit_price": "4.50",
        "foerdersatz": "0.5000",
        "occurred_on": "2026-07-02",
    }
    assert restored_log.after == {
        "booking_reference": restored_charge.booking_reference,
        "kind": Charge.Kind.FOOD,
        "description": "Frühstück",
        "quantity": "2.00",
        "unit_price": "4.50",
        "foerdersatz": "0.5000",
        "occurred_on": "2026-07-02",
    }


@pytest.mark.django_db
def test_editor_cannot_restore_deleted_booking(client):
    editor = UserFactory(username="editor")
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    charge = ChargeFactory(participant=participant, description="Doppelte Buchung")
    charge.deleted_at = timezone.now()
    charge.save(update_fields=["deleted_at"])
    deleted_log = BookingAuditLog.objects.create(
        participant=participant,
        charge=charge,
        action=BookingAuditLog.Action.DELETED,
        before={
            "kind": Charge.Kind.OTHER,
            "description": "Doppelte Buchung",
            "quantity": "1.00",
            "unit_price": "4.00",
            "foerdersatz": "0.0000",
            "occurred_on": None,
        },
        after={},
    )
    client.force_login(editor)

    response = client.post(reverse("booking-audit-restore", args=[deleted_log.pk]))

    charge.refresh_from_db()
    deleted_log.refresh_from_db()
    assert response.status_code == 302
    assert reverse("login") in response["Location"]
    assert deleted_log.charge == charge
    assert charge.deleted_at is not None
    assert Charge.objects.count() == 1
    assert BookingAuditLog.objects.count() == 1


@pytest.mark.django_db
def test_admin_cannot_restore_deleted_booking_without_participant(client):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    deleted_log = BookingAuditLog.objects.create(
        participant=None,
        charge=None,
        changed_by=admin,
        action=BookingAuditLog.Action.DELETED,
        before={
            "kind": Charge.Kind.OTHER,
            "description": "Nicht zuordenbar",
            "quantity": "1.00",
            "unit_price": "4.00",
            "foerdersatz": "0.0000",
            "occurred_on": None,
        },
        after={},
    )
    client.force_login(admin)

    response = client.post(reverse("booking-audit-restore", args=[deleted_log.pk]))

    deleted_log.refresh_from_db()
    assert response.status_code == 302
    assert response["Location"] == reverse("camp-list")
    assert deleted_log.charge is None
    assert Charge.objects.count() == 0
    assert BookingAuditLog.objects.count() == 1
