from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.urls import resolve, reverse
from django.utils import timezone

from billing.kiosk_access import KIOSK_FAMILY_MEMBER_SESSION_KEY, KIOSK_PARTICIPANT_SESSION_KEY
from billing.models import (
    Charge,
    KioskActionAuditLog,
    MealSignup,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    PriceRule,
    PushMessage,
    PushSubscription,
    Settlement,
    SettlementRun,
)
from billing.views import _kiosk_checkin_participants, _kiosk_meal_targets, _linked_booking_participants
from tests.factories import CampFactory, ParticipantFactory, PriceRuleFactory, SuperUserFactory


def test_kiosk_action_audit_log_model_is_registered():
    """Partner actions need a dedicated participant-aware audit trail."""
    assert "kioskactionauditlog" in apps.all_models["billing"]


def test_kiosk_action_audit_log_is_read_only_in_admin():
    model_admin = admin.site._registry[KioskActionAuditLog]
    assert model_admin.has_add_permission(None) is False
    assert model_admin.has_change_permission(None) is False
    assert model_admin.has_delete_permission(None) is False


@pytest.mark.django_db
def test_kiosk_action_audit_log_rejects_instance_and_queryset_mutation():
    participant = ParticipantFactory()
    partner = ParticipantFactory(camp=participant.camp)
    audit_log = KioskActionAuditLog.objects.create(
        camp=participant.camp,
        actor_participant=participant,
        target_participant=partner,
        action=KioskActionAuditLog.Action.LINK_INVITED,
        description="Unveränderlicher Eintrag",
    )

    audit_log.description = "Manipuliert"
    with pytest.raises(ValidationError):
        audit_log.save()
    with pytest.raises(ValidationError):
        KioskActionAuditLog.objects.filter(pk=audit_log.pk).update(description="Manipuliert")
    with pytest.raises(ValidationError):
        KioskActionAuditLog.objects.filter(pk=audit_log.pk).delete()


@pytest.mark.django_db
def test_camp_with_kiosk_audit_history_cannot_be_deleted():
    participant = ParticipantFactory()
    partner = ParticipantFactory(camp=participant.camp)
    audit_log = KioskActionAuditLog.objects.create(
        camp=participant.camp,
        actor_participant=participant,
        target_participant=partner,
        action=KioskActionAuditLog.Action.LINK_INVITED,
        description="Partner-Vollmacht angefragt.",
    )

    with pytest.raises(ProtectedError):
        participant.camp.delete()

    assert KioskActionAuditLog.objects.filter(pk=audit_log.pk).exists()


def test_partner_activity_routes_exist_for_both_kiosk_modes():
    assert resolve("/kiosk/partners/").url_name == "kiosk-partner-activity"
    assert resolve("/central/kiosk/partners/").url_name == "central-kiosk-partner-activity"
    assert (
        resolve("/kiosk/participants/42/export/settlement.pdf").url_name == "kiosk-participant-current-settlement-pdf"
    )
    assert (
        resolve("/central/kiosk/participants/42/export/settlement.pdf").url_name
        == "central-kiosk-participant-current-settlement-pdf"
    )


@pytest.mark.django_db
def test_partner_activity_page_explains_scope_and_lists_link(kiosk_client):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    partner = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-partner-activity"))

    assert response.status_code == 200
    assert "billing/kiosk_partner_activity.html" in [template.name for template in response.templates]
    content = response.content.decode("utf-8")
    assert "Partner &amp; Aktivitäten" in content
    assert "Grace Hopper" in content
    assert "Abrechnung einschließlich Familienpositionen" in content
    assert "Anreise, Abreise und Übernachtungen" in content


@pytest.mark.django_db
def test_linked_households_are_prefetched_once_and_reused_by_target_builders(django_assert_num_queries):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)
    own_child = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Eigenes",
        last_name="Kind",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    expected_partner_tokens = []
    for index in range(3):
        partner = ParticipantFactory(camp=camp)
        ParticipantBookingLink.objects.create(
            inviter=participant,
            invitee=partner,
            status=ParticipantBookingLink.Status.ACCEPTED,
        )
        partner_child = ParticipantFamilyMember.objects.create(
            guardian=partner,
            first_name=f"Partnerkind{index}",
            last_name="Muster",
            role=ParticipantFamilyMember.Role.CHILD,
        )
        expected_partner_tokens.extend([f"participant-{partner.pk}", f"family-{partner_child.pk}"])

    own_family_members = list(participant.family_members.filter(is_active=True))
    with django_assert_num_queries(2):
        linked_participants = _linked_booking_participants(participant)
    with django_assert_num_queries(0):
        meal_targets = _kiosk_meal_targets(
            participant,
            family_members=own_family_members,
            linked_participants=linked_participants,
        )
        checkin_targets = _kiosk_checkin_participants(
            participant,
            family_members=own_family_members,
            linked_participants=linked_participants,
        )

    expected_tokens = {f"participant-{participant.pk}", f"family-{own_child.pk}", *expected_partner_tokens}
    assert {target["token"] for target in meal_targets} == expected_tokens
    assert {target["token"] for target in checkin_targets} == expected_tokens


@pytest.mark.django_db
def test_kiosk_home_links_to_partner_activity_page(kiosk_client):
    participant = ParticipantFactory()
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert f'href="{reverse("kiosk-partner-activity")}"'.encode() in response.content
    assert b"Partner &amp; Aktivit\xc3\xa4ten" in response.content


@pytest.mark.django_db
def test_quick_drink_dialog_lists_the_accepted_partner_household(kiosk_client):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    partner = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    partner_child = ParticipantFamilyMember.objects.create(
        guardian=partner,
        first_name="Kind",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    content = response.content.decode("utf-8")
    quick_dialog = content.split('<dialog id="quick-dialog"', 1)[1].split('<dialog id="food-dialog"', 1)[0]
    assert f'value="participant-{partner.pk}"' in quick_dialog
    assert f'value="family-{partner_child.pk}"' in quick_dialog
    assert "Grace Hopper · Verknüpft" in quick_dialog
    assert "Kind Hopper · Partnerkonto · Kind" in quick_dialog


@pytest.mark.django_db
def test_partner_activity_page_contains_invite_and_revoke_controls(kiosk_client):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    partner = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-partner-activity"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'name="action" value="booking_link_invite"' in content
    assert 'name="action" value="booking_link_revoke"' in content
    assert f'name="booking_link_id" value="{link.pk}"' in content
    assert f'data-dialog-target="partner-revoke-dialog-{link.pk}"' in content
    assert "Vollmacht wirklich widerrufen?" in content
    assert list(response.context["booking_link_form"].fields["participant"].queryset) == []


@pytest.mark.django_db
def test_companion_cannot_manage_partner_authorizations(kiosk_client):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)
    companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    invitee = ParticipantFactory(camp=camp)
    invitation = ParticipantBookingLink.objects.create(inviter=invitee, invitee=participant)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = companion.pk
    session.save()

    home_response = kiosk_client.get(reverse("kiosk-home"))
    response = kiosk_client.post(
        reverse("kiosk-partner-activity"),
        {
            "action": "booking_link_invite",
            "link-participant": invitee.pk,
        },
    )

    assert f'name="booking_link_id" value="{invitation.pk}"'.encode() not in home_response.content
    assert response.status_code == 403
    assert ParticipantBookingLink.objects.count() == 1


@pytest.mark.django_db
def test_pending_partner_invitation_cannot_be_accepted_after_inviter_is_archived(kiosk_client):
    camp = CampFactory(is_active=True)
    inviter = ParticipantFactory(camp=camp, first_name="Archiviert", last_name="Muster")
    invitee = ParticipantFactory(camp=camp)
    invitation = ParticipantBookingLink.objects.create(inviter=inviter, invitee=invitee)
    inviter.archived_at = timezone.now()
    inviter.save(update_fields=["archived_at", "updated_at"])
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = invitee.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-partner-activity"),
        {
            "action": "booking_link_accept",
            "booking_link_id": invitation.pk,
        },
    )

    invitation.refresh_from_db()
    assert response.status_code == 200
    assert invitation.status == ParticipantBookingLink.Status.PENDING
    assert not KioskActionAuditLog.objects.exists()
    assert inviter.full_name.encode() not in response.content


@pytest.mark.django_db
def test_accepted_partner_can_download_live_and_current_camp_snapshot(kiosk_client):
    camp = CampFactory(is_active=True, show_kiosk_invoices=True)
    participant = ParticipantFactory(camp=camp)
    partner = ParticipantFactory(camp=camp)
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    run = SettlementRun.objects.create(camp=camp, version=1, calculated_by=SuperUserFactory())
    snapshot = Settlement.objects.create(
        run=run,
        participant=partner,
        total_due=Decimal("42.00"),
        total_paid=Decimal("0.00"),
        total_advanced=Decimal("0.00"),
        balance=Decimal("42.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    live_response = kiosk_client.get(reverse("kiosk-participant-current-settlement-pdf", args=[partner.pk]))
    snapshot_response = kiosk_client.get(reverse("kiosk-settlement-pdf", args=[snapshot.pk]))

    assert live_response.status_code == 200
    assert live_response["Content-Type"] == "application/pdf"
    assert snapshot_response.status_code == 200
    assert snapshot_response["Content-Type"] == "application/pdf"


@pytest.mark.django_db
def test_partner_authorization_never_exposes_snapshot_from_another_camp(kiosk_client):
    camp = CampFactory(is_active=True, show_kiosk_invoices=True)
    other_camp = CampFactory(
        name="Fremdes Lager",
        year=2024,
        is_active=False,
        show_kiosk_invoices=True,
    )
    participant = ParticipantFactory(camp=camp)
    partner = ParticipantFactory(camp=camp)
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    foreign_run = SettlementRun.objects.create(camp=other_camp, version=1, calculated_by=SuperUserFactory())
    foreign_snapshot = Settlement.objects.create(
        run=foreign_run,
        participant=partner,
        total_due=Decimal("42.00"),
        total_paid=Decimal("0.00"),
        total_advanced=Decimal("0.00"),
        balance=Decimal("42.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    pdf_response = kiosk_client.get(reverse("kiosk-settlement-pdf", args=[foreign_snapshot.pk]))
    page_response = kiosk_client.get(reverse("kiosk-partner-activity"))

    assert pdf_response.status_code == 403
    assert reverse("kiosk-settlement-pdf", args=[foreign_snapshot.pk]).encode() not in page_response.content


@pytest.mark.django_db
@pytest.mark.parametrize("link_status", [ParticipantBookingLink.Status.REVOKED, ParticipantBookingLink.Status.PENDING])
def test_non_accepted_partner_cannot_download_live_invoice(kiosk_client, link_status):
    camp = CampFactory(is_active=True, show_kiosk_invoices=True)
    participant = ParticipantFactory(camp=camp)
    partner = ParticipantFactory(camp=camp)
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=link_status,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-participant-current-settlement-pdf", args=[partner.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_cross_camp_partner_link_never_authorizes_invoice(kiosk_client):
    camp = CampFactory(is_active=True, show_kiosk_invoices=True)
    other_camp = CampFactory(
        name="Früheres Lager",
        year=2024,
        is_active=False,
        show_kiosk_invoices=True,
    )
    participant = ParticipantFactory(camp=camp)
    partner = ParticipantFactory(camp=other_camp)
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-participant-current-settlement-pdf", args=[partner.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_partner_activity_page_shows_full_partner_invoice_and_pdf_links(kiosk_client):
    camp = CampFactory(is_active=True, show_kiosk_invoices=True)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    partner = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    Charge.objects.create(
        participant=partner,
        kind=Charge.Kind.FOOD,
        description="Abendessen für Kind Hopper",
        quantity=Decimal("1.00"),
        unit_price=Decimal("8.00"),
    )
    run = SettlementRun.objects.create(camp=camp, version=1, calculated_by=SuperUserFactory())
    snapshot = Settlement.objects.create(
        run=run,
        participant=partner,
        total_due=Decimal("8.00"),
        total_paid=Decimal("0.00"),
        total_advanced=Decimal("0.00"),
        balance=Decimal("8.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-partner-activity"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Abendessen für Kind Hopper" in content
    assert reverse("kiosk-participant-current-settlement-pdf", args=[partner.pk]) in content
    assert reverse("kiosk-settlement-pdf", args=[snapshot.pk]) in content


@pytest.mark.django_db
def test_linked_household_checkin_records_actual_actor_and_before_after(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(
        is_active=True,
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 14),
    )
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Charles",
        last_name="Babbage",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    partner = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    partner_child = ParticipantFamilyMember.objects.create(
        guardian=partner,
        first_name="Kind",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = companion.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [f"family-{partner_child.pk}"],
            f"arrival_date_family-{partner_child.pk}": "2026-07-03",
            f"departure_date_family-{partner_child.pk}": "2026-07-09",
        },
    )

    assert response.status_code == 302
    audit_log = KioskActionAuditLog.objects.get()
    assert audit_log.action == KioskActionAuditLog.Action.CHECKIN_UPDATED
    assert audit_log.actor_participant == participant
    assert audit_log.actor_family_member == companion
    assert audit_log.target_participant == partner
    assert audit_log.target_family_member == partner_child
    assert audit_log.booking_link == link
    assert audit_log.before == {
        "arrival_date": None,
        "departure_date": None,
    }
    assert audit_log.after == {
        "arrival_date": "2026-07-03",
        "departure_date": "2026-07-09",
    }
    assert partner_child.full_name not in audit_log.description
    assert partner_child.full_name not in str(audit_log.before)
    assert partner_child.full_name not in str(audit_log.after)

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = partner.pk
    session.pop(KIOSK_FAMILY_MEMBER_SESSION_KEY, None)
    session.save()
    activity_response = kiosk_client.get(reverse("kiosk-partner-activity"))
    activity_content = activity_response.content.decode("utf-8")
    assert activity_response.status_code == 200
    assert "Charles Babbage" in activity_content
    assert "Kind Hopper" in activity_content
    assert "Anreise: – → 03.07.2026" in activity_content
    assert "Abreise: – → 09.07.2026" in activity_content


@pytest.mark.django_db
def test_linked_family_quick_booking_and_cancellation_are_audited(kiosk_client):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    partner = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    partner_child = ParticipantFamilyMember.objects.create(
        guardian=partner,
        first_name="Kind",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    rule = PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        name="Wasser",
        unit_price=Decimal("1.50"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    booking_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "quick",
            "quick-price_rule": rule.pk,
            "quick-quantity": 1,
            "quick-target": [f"family-{partner_child.pk}"],
        },
    )

    assert booking_response.status_code == 302
    charge = Charge.objects.get()
    assert charge.participant == partner
    assert partner_child.full_name in charge.description
    created_log = KioskActionAuditLog.objects.get(action=KioskActionAuditLog.Action.QUICK_BOOKED)
    assert created_log.target_participant == partner
    assert created_log.target_family_member == partner_child
    assert created_log.booking_link == link
    assert created_log.before == {}
    assert created_log.after["booking_reference"] == charge.booking_reference
    assert created_log.after["deleted_at"] is None
    assert partner_child.full_name not in created_log.description
    assert partner_child.full_name not in str(created_log.after)

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = partner.pk
    session.save()
    cancellation_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "quick_cancel",
            "charge_id": charge.pk,
        },
    )

    assert cancellation_response.status_code == 302
    cancelled_log = KioskActionAuditLog.objects.get(action=KioskActionAuditLog.Action.QUICK_CANCELLED)
    assert cancelled_log.actor_participant == partner
    assert cancelled_log.target_participant == partner
    assert cancelled_log.target_family_member == partner_child
    assert cancelled_log.booking_link == link
    assert cancelled_log.before["deleted_at"] is None
    assert cancelled_log.after["deleted_at"] is not None
    assert partner_child.full_name not in cancelled_log.description
    assert partner_child.full_name not in str(cancelled_log.before)
    assert partner_child.full_name not in str(cancelled_log.after)

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    activity_response = kiosk_client.get(reverse("kiosk-partner-activity"))
    assert "storniert" in activity_response.content.decode("utf-8")


@pytest.mark.django_db
def test_partner_can_cancel_partners_own_recent_quick_booking(
    kiosk_client,
    django_capture_on_commit_callbacks,
    settings,
):
    settings.WEB_PUSH_ENABLED = True
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    partner = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    booking_link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    charge = Charge.objects.create(
        participant=partner,
        kiosk_booked_by=partner,
        kind=Charge.Kind.DRINK,
        description="Wasser (Kiosk)",
        quantity=Decimal("1.00"),
        unit_price=Decimal("1.50"),
    )
    PushSubscription.objects.create(
        participant=partner,
        endpoint="https://push.example.test/partner-quick-cancel",
        p256dh="key",
        auth="secret",
        categories=["booking_links"],
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    page_response = kiosk_client.get(reverse("kiosk-home"))

    visible_charge = next(item for item in page_response.context["recent_quick_charges"] if item.pk == charge.pk)
    assert visible_charge.is_kiosk_cancelable is True
    assert partner.full_name in page_response.content.decode("utf-8")

    with django_capture_on_commit_callbacks(execute=True):
        cancellation_response = kiosk_client.post(
            reverse("kiosk-home"),
            {
                "action": "quick_cancel",
                "charge_id": charge.pk,
            },
        )

    charge.refresh_from_db()
    assert cancellation_response.status_code == 302
    assert charge.deleted_at is not None
    audit_log = KioskActionAuditLog.objects.get(action=KioskActionAuditLog.Action.QUICK_CANCELLED)
    assert audit_log.actor_participant == participant
    assert audit_log.target_participant == partner
    assert audit_log.booking_link == booking_link
    assert audit_log.before["deleted_at"] is None
    assert audit_log.after["deleted_at"] is not None
    message = PushMessage.objects.get()
    assert message.subscription.participant == partner
    assert message.title == "Partnerkonto geändert"


@pytest.mark.django_db
def test_linked_family_meal_booking_and_retraction_are_audited(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 6, 30, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(
        is_active=True,
        starts_on=date(2026, 6, 30),
        ends_on=date(2026, 7, 14),
    )
    participant = ParticipantFactory(camp=camp)
    partner = ParticipantFactory(camp=camp)
    partner_child = ParticipantFamilyMember.objects.create(
        guardian=partner,
        first_name="Kind",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=True,
        applies_to_adults=False,
        name="Abendessen Kind",
        unit_price=Decimal("5.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    booking_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": "2026-07-02",
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
            "meal-target": [f"family-{partner_child.pk}"],
            f"meal-variant-family-{partner_child.pk}": MealSignup.Variant.NORMAL_CHILD,
        },
    )

    assert booking_response.status_code == 302
    signup = MealSignup.objects.get(participant=partner, family_member=partner_child)
    created_log = KioskActionAuditLog.objects.get(action=KioskActionAuditLog.Action.MEAL_BOOKED)
    assert created_log.target_participant == partner
    assert created_log.target_family_member == partner_child
    assert created_log.booking_link == link
    assert created_log.after["status"] == MealSignup.Status.ACTIVE
    assert partner_child.full_name not in created_log.description
    assert partner_child.full_name not in str(created_log.after)

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = partner.pk
    session.save()
    retraction_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal_retract",
            "meal_signup_id": signup.pk,
        },
    )

    assert retraction_response.status_code == 302
    retracted_log = KioskActionAuditLog.objects.get(action=KioskActionAuditLog.Action.MEAL_RETRACTED)
    assert retracted_log.actor_participant == partner
    assert retracted_log.target_participant == partner
    assert retracted_log.target_family_member == partner_child
    assert retracted_log.booking_link == link
    assert retracted_log.before["status"] == MealSignup.Status.ACTIVE
    assert retracted_log.after["status"] == MealSignup.Status.RETRACTED
    assert partner_child.full_name not in retracted_log.description
    assert partner_child.full_name not in str(retracted_log.before)
    assert partner_child.full_name not in str(retracted_log.after)


@pytest.mark.django_db
def test_charge_less_partner_meal_retraction_is_audited_and_notified(
    kiosk_client,
    django_capture_on_commit_callbacks,
    monkeypatch,
    settings,
):
    settings.WEB_PUSH_ENABLED = True
    fixed_now = timezone.make_aware(datetime(2026, 6, 30, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(
        is_active=True,
        starts_on=date(2026, 6, 30),
        ends_on=date(2026, 7, 14),
    )
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    partner = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    booking_link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    signup = MealSignup.objects.create(
        participant=partner,
        meal_date=date(2026, 7, 2),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )
    PushSubscription.objects.create(
        participant=partner,
        endpoint="https://push.example.test/partner-meal-retract",
        p256dh="key",
        auth="secret",
        categories=["booking_links"],
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    page_response = kiosk_client.get(reverse("kiosk-home"))
    visible_signup = next(item for item in page_response.context["meal_signups"] if item.pk == signup.pk)

    assert visible_signup.requires_partner_retraction_confirmation is True
    assert visible_signup.retraction_confirmation_token
    page_content = page_response.content.decode("utf-8")
    assert "data-open-meal-retract-dialog" in page_content
    assert 'id="meal-retract-dialog"' in page_content

    unconfirmed_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal_retract",
            "meal_signup_id": signup.pk,
        },
    )

    signup.refresh_from_db()
    assert unconfirmed_response.status_code == 200
    assert signup.status == MealSignup.Status.ACTIVE
    assert not KioskActionAuditLog.objects.filter(action=KioskActionAuditLog.Action.MEAL_RETRACTED).exists()
    assert not PushMessage.objects.exists()

    with django_capture_on_commit_callbacks(execute=True):
        response = kiosk_client.post(
            reverse("kiosk-home"),
            {
                "action": "meal_retract",
                "meal_signup_id": signup.pk,
                "meal_retraction_token": visible_signup.retraction_confirmation_token,
            },
        )

    signup.refresh_from_db()
    assert response.status_code == 302
    assert signup.status == MealSignup.Status.RETRACTED
    audit_log = KioskActionAuditLog.objects.get(action=KioskActionAuditLog.Action.MEAL_RETRACTED)
    assert audit_log.actor_participant == participant
    assert audit_log.target_participant == partner
    assert audit_log.booking_link == booking_link
    assert audit_log.charge is None
    assert audit_log.before["status"] == MealSignup.Status.ACTIVE
    assert audit_log.after["status"] == MealSignup.Status.RETRACTED
    assert audit_log.description == "Essensanmeldung zurückgenommen."
    message = PushMessage.objects.get()
    assert message.subscription.participant == partner
    assert message.title == "Partnerkonto geändert"


@pytest.mark.django_db
def test_paid_partner_meal_retraction_requires_signed_confirmation(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 6, 30, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(
        is_active=True,
        starts_on=date(2026, 6, 30),
        ends_on=date(2026, 7, 14),
    )
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    partner = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    charge = Charge.objects.create(
        participant=partner,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=Decimal("1.00"),
        unit_price=Decimal("8.00"),
        occurred_on=date(2026, 7, 2),
        kiosk_booked_by=partner,
    )
    signup = MealSignup.objects.create(
        participant=partner,
        meal_date=date(2026, 7, 2),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        charge=charge,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    page_response = kiosk_client.get(reverse("kiosk-home"))
    visible_signup = next(item for item in page_response.context["meal_signups"] if item.pk == signup.pk)
    content = page_response.content.decode("utf-8")

    assert visible_signup.requires_partner_retraction_confirmation is True
    assert visible_signup.retraction_confirmation_token
    assert f'data-meal-signup-id="{signup.pk}"' in content
    assert 'data-meal-retract-cost="8,00 €"' in content

    unconfirmed_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal_retract",
            "meal_signup_id": signup.pk,
        },
    )

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert unconfirmed_response.status_code == 200
    assert signup.status == MealSignup.Status.ACTIVE
    assert charge.deleted_at is None

    confirmed_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal_retract",
            "meal_signup_id": signup.pk,
            "meal_retraction_token": visible_signup.retraction_confirmation_token,
        },
    )

    signup.refresh_from_db()
    charge.refresh_from_db()
    assert confirmed_response.status_code == 302
    assert signup.status == MealSignup.Status.RETRACTED
    assert charge.deleted_at is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kind", "meal_type", "is_default"),
    [
        (PriceRule.Kind.DRINK, "", False),
        (PriceRule.Kind.MEAL, PriceRule.MealType.SNACK, True),
    ],
)
def test_quick_booking_rejects_rule_that_does_not_apply_to_selected_partner_child(
    kiosk_client,
    kind,
    meal_type,
    is_default,
):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp, is_child=False, is_companion=False)
    partner = ParticipantFactory(camp=camp)
    partner_child = ParticipantFamilyMember.objects.create(
        guardian=partner,
        first_name="Kind",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    rule = PriceRuleFactory(
        camp=camp,
        kind=kind,
        meal_type=meal_type,
        is_default=is_default,
        applies_to_children=False,
        applies_to_adults=True,
        applies_to_companions=False,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "quick",
            "quick-price_rule": rule.pk,
            "quick-quantity": 1,
            "quick-target": [f"family-{partner_child.pk}"],
        },
    )

    assert response.status_code == 200
    expected_error = "Die Preisregel ist nicht für alle ausgewählten Personen verfügbar.".encode()
    assert expected_error in response.content
    assert not Charge.objects.exists()
    assert not KioskActionAuditLog.objects.exists()


@pytest.mark.django_db
def test_quick_food_booking_resolves_the_selected_partner_child_price(kiosk_client):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp, is_child=False, is_companion=False)
    partner = ParticipantFactory(camp=camp)
    partner_child = ParticipantFamilyMember.objects.create(
        guardian=partner,
        first_name="Kind",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    adult_rule = PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=PriceRule.MealType.SNACK,
        is_default=True,
        name="Mittagssnack Erwachsene",
        unit_price=Decimal("8.00"),
        applies_to_children=False,
        applies_to_adults=True,
        applies_to_companions=False,
    )
    child_rule = PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=PriceRule.MealType.SNACK,
        is_default=True,
        name="Mittagssnack Kinder",
        unit_price=Decimal("4.00"),
        applies_to_children=True,
        applies_to_adults=False,
        applies_to_companions=False,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "quick",
            "quick-price_rule": adult_rule.pk,
            "quick-quantity": 1,
            "quick-target": [f"family-{partner_child.pk}"],
        },
    )

    assert response.status_code == 302
    charge = Charge.objects.get()
    assert charge.participant == partner
    assert charge.unit_price == child_rule.unit_price
    assert child_rule.name in charge.description


@pytest.mark.django_db
def test_adult_can_select_child_only_drink_for_authorized_partner_child(kiosk_client):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp, is_child=False, is_companion=False)
    partner = ParticipantFactory(camp=camp)
    partner_child = ParticipantFamilyMember.objects.create(
        guardian=partner,
        first_name="Kind",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    child_rule = PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        name="Kinder-Apfelsaft",
        unit_price=Decimal("1.00"),
        applies_to_children=True,
        applies_to_adults=False,
        applies_to_companions=False,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    page_response = kiosk_client.get(reverse("kiosk-home"))

    assert child_rule in list(page_response.context["drink_rules"])

    booking_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "quick",
            "quick-price_rule": child_rule.pk,
            "quick-quantity": 1,
            "quick-target": [f"family-{partner_child.pk}"],
        },
    )

    assert booking_response.status_code == 302
    charge = Charge.objects.get()
    assert charge.participant == partner
    assert charge.unit_price == Decimal("1.00")
    assert partner_child.full_name in charge.description


@pytest.mark.django_db
def test_multi_account_quick_booking_requires_exact_cost_confirmation(kiosk_client):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp, is_child=False, is_companion=False)
    partner = ParticipantFactory(camp=camp)
    partner_child = ParticipantFamilyMember.objects.create(
        guardian=partner,
        first_name="Kind",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    adult_rule = PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=PriceRule.MealType.SNACK,
        is_default=True,
        name="Snack Erwachsene",
        unit_price=Decimal("4.00"),
        applies_to_children=False,
        applies_to_adults=True,
        applies_to_companions=False,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=PriceRule.MealType.SNACK,
        is_default=True,
        name="Snack Kinder",
        unit_price=Decimal("2.00"),
        applies_to_children=True,
        applies_to_adults=False,
        applies_to_companions=False,
    )
    target_tokens = [
        f"participant-{participant.pk}",
        f"family-{partner_child.pk}",
    ]
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    request_data = {
        "action": "quick",
        "quick-price_rule": adult_rule.pk,
        "quick-quantity": 2,
        "quick-targets-submitted": "1",
        "quick-target": target_tokens,
    }

    preview_response = kiosk_client.post(reverse("kiosk-home"), request_data)

    assert preview_response.status_code == 200
    assert not Charge.objects.exists()
    confirmation = preview_response.context["quick_confirmation"]
    assert confirmation["quantity"] == 2
    assert confirmation["target_tokens"] == target_tokens
    assert confirmation["total"] == Decimal("12.00")
    assert confirmation["token"]
    assert confirmation["changed"] is False
    assert [(item["name"], item["unit_price"], item["total"]) for item in confirmation["items"]] == [
        (participant.full_name, Decimal("4.00"), Decimal("8.00")),
        (partner_child.full_name, Decimal("2.00"), Decimal("4.00")),
    ]
    content = preview_response.content.decode("utf-8")
    assert "Mehrfachbuchung bestätigen" in content
    assert participant.full_name in content
    assert partner_child.full_name in content
    assert "12,00 €" in content

    reduced_target_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            **request_data,
            "quick-target": [target_tokens[0]],
            "quick-confirmed": "1",
            "quick-confirmation-token": confirmation["token"],
        },
    )

    assert reduced_target_response.status_code == 200
    assert not Charge.objects.exists()
    reduced_target_confirmation = reduced_target_response.context["quick_confirmation"]
    assert reduced_target_confirmation["changed"] is True
    assert reduced_target_confirmation["target_tokens"] == [target_tokens[0]]
    assert reduced_target_confirmation["total"] == Decimal("8.00")

    tampered_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            **request_data,
            "quick-quantity": 3,
            "quick-confirmed": "1",
            "quick-confirmation-token": confirmation["token"],
        },
    )

    assert tampered_response.status_code == 200
    assert not Charge.objects.exists()
    tampered_confirmation = tampered_response.context["quick_confirmation"]
    assert tampered_confirmation["changed"] is True
    assert tampered_confirmation["quantity"] == 3
    assert tampered_confirmation["total"] == Decimal("18.00")
    assert "Buchungsdaten wurden aktualisiert" in tampered_response.content.decode("utf-8")

    adult_rule.unit_price = Decimal("5.00")
    adult_rule.save(update_fields=["unit_price", "updated_at"])
    stale_price_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            **request_data,
            "quick-confirmed": "1",
            "quick-confirmation-token": confirmation["token"],
        },
    )

    assert stale_price_response.status_code == 200
    assert not Charge.objects.exists()
    updated_confirmation = stale_price_response.context["quick_confirmation"]
    assert updated_confirmation["changed"] is True
    assert updated_confirmation["total"] == Decimal("14.00")
    assert updated_confirmation["token"] != confirmation["token"]

    confirmation_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            **request_data,
            "quick-confirmed": "1",
            "quick-confirmation-token": updated_confirmation["token"],
        },
    )

    assert confirmation_response.status_code == 302
    charges = list(Charge.objects.order_by("unit_price"))
    assert len(charges) == 2
    assert [(charge.participant, charge.quantity, charge.unit_price) for charge in charges] == [
        (partner, Decimal("2.00"), Decimal("2.00")),
        (participant, Decimal("2.00"), Decimal("5.00")),
    ]
    assert sum(charge.kiosk_confirmation_nonce is not None for charge in charges) == 1

    replay_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            **request_data,
            "quick-confirmed": "1",
            "quick-confirmation-token": updated_confirmation["token"],
        },
        follow=True,
    )

    assert replay_response.status_code == 200
    assert Charge.objects.count() == 2
    assert "Diese Bestätigung wurde bereits verarbeitet." in replay_response.content.decode("utf-8")


@pytest.mark.django_db
def test_partner_meal_signup_charge_is_excluded_from_quick_cancellation(kiosk_client):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)
    partner = ParticipantFactory(camp=camp)
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    charge = Charge.objects.create(
        participant=partner,
        kiosk_booked_by=partner,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=Decimal("1.00"),
        unit_price=Decimal("8.00"),
        occurred_on=timezone.localdate() + timedelta(days=1),
    )
    signup = MealSignup.objects.create(
        participant=partner,
        meal_date=charge.occurred_on,
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        status=MealSignup.Status.ACTIVE,
        charge=charge,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    page_response = kiosk_client.get(reverse("kiosk-home"))

    assert charge.pk not in {item.pk for item in page_response.context["recent_quick_charges"]}

    cancellation_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "quick_cancel",
            "charge_id": charge.pk,
        },
    )

    assert cancellation_response.status_code == 200
    charge.refresh_from_db()
    signup.refresh_from_db()
    assert charge.deleted_at is None
    assert signup.status == MealSignup.Status.ACTIVE


@pytest.mark.django_db
def test_revoked_partner_authorization_immediately_removes_cross_account_cancellation(kiosk_client):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)
    partner = ParticipantFactory(camp=camp)
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.REVOKED,
    )
    charge = Charge.objects.create(
        participant=partner,
        kiosk_booked_by=participant,
        kind=Charge.Kind.DRINK,
        description="Wasser",
        quantity=Decimal("1.00"),
        unit_price=Decimal("1.50"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    page_response = kiosk_client.get(reverse("kiosk-home"))

    assert page_response.status_code == 200
    visible_charge = next(item for item in page_response.context["recent_quick_charges"] if item.pk == charge.pk)
    assert visible_charge.is_kiosk_cancelable is False

    cancellation_response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "quick_cancel",
            "charge_id": charge.pk,
        },
    )
    charge.refresh_from_db()
    assert cancellation_response.status_code == 200
    assert charge.deleted_at is None
    assert not KioskActionAuditLog.objects.exists()


@pytest.mark.django_db
def test_revoke_closes_every_accepted_authorization_for_the_partner_pair(kiosk_client):
    camp = CampFactory(is_active=True, show_kiosk_invoices=True)
    participant = ParticipantFactory(camp=camp)
    partner = ParticipantFactory(camp=camp)
    selected_link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    duplicate_link = ParticipantBookingLink.objects.create(
        inviter=partner,
        invitee=participant,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-partner-activity"),
        {
            "action": "booking_link_revoke",
            "booking_link_id": selected_link.pk,
        },
    )

    assert response.status_code == 302
    selected_link.refresh_from_db()
    duplicate_link.refresh_from_db()
    assert selected_link.status == ParticipantBookingLink.Status.REVOKED
    assert duplicate_link.status == ParticipantBookingLink.Status.REVOKED
    assert kiosk_client.get(reverse("kiosk-participant-current-settlement-pdf", args=[partner.pk])).status_code == 403
