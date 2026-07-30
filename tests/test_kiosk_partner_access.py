from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.apps import apps
from django.conf import settings as django_settings
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.backends.postgresql.base import DatabaseWrapper
from django.db.models import QuerySet
from django.db.models.deletion import ProtectedError
from django.urls import resolve, reverse
from django.utils import timezone

from billing.forms import KioskBookingLinkInviteForm
from billing.kiosk_access import KIOSK_FAMILY_MEMBER_SESSION_KEY, KIOSK_PARTICIPANT_SESSION_KEY
from billing.models import (
    Charge,
    KioskActionAuditLog,
    MealSignup,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    PriceRule,
    PushMessage,
    PushSubscription,
    Settlement,
    SettlementRun,
)
from billing.views import (
    _book_meal_for_target,
    _kiosk_checkin_participants,
    _kiosk_meal_targets,
    _linked_booking_participants,
    _retract_meal_signup,
    _sign_kiosk_meal_retraction,
)
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
def test_kiosk_home_discloses_full_partner_scope_before_invitation_acceptance(kiosk_client):
    camp = CampFactory(is_active=True)
    inviter = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    invitee = ParticipantFactory(camp=camp)
    ParticipantBookingLink.objects.create(inviter=inviter, invitee=invitee)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = invitee.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = " ".join(response.content.decode("utf-8").split())
    accept_button_index = content.index('value="booking_link_accept"')
    disclosed_scope = (
        "Abrechnung einschließlich Familienpositionen und PDF einsehen",
        "Getränke und Essen für das Partnerkonto buchen oder stornieren",
        "Anreise, Abreise und Übernachtungen des Partnerhaushalts verwalten",
        "Auch aktive Begleitpersonen beider Hauptkonten können diese Rechte mit ihrer eigenen PIN ausüben.",
        "Im Aktivitätsprotokoll wird die handelnde Begleitperson als Akteur genannt.",
        "PINs, Stammdaten, weitere Partnerfreigaben und Adminfunktionen bleiben ausgeschlossen.",
    )
    assert "Grace Hopper" in content
    assert all(content.index(scope_item) < accept_button_index for scope_item in disclosed_scope)


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
def test_partner_invitation_rechecks_duplicates_after_locking_the_pair(kiosk_client, monkeypatch):
    camp = CampFactory(is_active=True)
    invitee = ParticipantFactory(camp=camp)
    inviter = ParticipantFactory(camp=camp)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = inviter.pk
    session.save()
    original_is_valid = KioskBookingLinkInviteForm.is_valid
    original_fetch_all = QuerySet._fetch_all
    duplicate_injected = False
    participant_lock_events = []

    def inject_concurrent_invitation(form):
        nonlocal duplicate_injected
        is_valid = original_is_valid(form)
        if is_valid and not duplicate_injected:
            duplicate_injected = True
            ParticipantBookingLink.objects.create(inviter=invitee, invitee=inviter)
        return is_valid

    def capture_participant_lock(queryset):
        was_unfetched = queryset._result_cache is None
        original_fetch_all(queryset)
        if was_unfetched and queryset.query.select_for_update and queryset.model is Participant:
            participant_lock_events.append(tuple(instance.pk for instance in queryset._result_cache))

    monkeypatch.setattr(KioskBookingLinkInviteForm, "is_valid", inject_concurrent_invitation)
    monkeypatch.setattr(QuerySet, "_fetch_all", capture_participant_lock)

    response = kiosk_client.post(
        reverse("kiosk-partner-activity"),
        {
            "action": "booking_link_invite",
            "link-participant": invitee.pk,
        },
    )

    assert response.status_code == 200
    assert ParticipantBookingLink.objects.count() == 1
    assert participant_lock_events == [tuple(sorted((inviter.pk, invitee.pk)))]
    assert "Zwischen diesen Teilnehmern besteht bereits eine offene Verknüpfung." in response.content.decode()


@pytest.mark.django_db
def test_accepting_partner_invitation_closes_duplicate_pending_invitations(kiosk_client):
    camp = CampFactory(is_active=True)
    inviter = ParticipantFactory(camp=camp)
    invitee = ParticipantFactory(camp=camp)
    selected_link = ParticipantBookingLink.objects.create(inviter=inviter, invitee=invitee)
    duplicate_link = ParticipantBookingLink.objects.create(inviter=invitee, invitee=inviter)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = invitee.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-partner-activity"),
        {
            "action": "booking_link_accept",
            "booking_link_id": selected_link.pk,
        },
    )

    assert response.status_code == 302
    selected_link.refresh_from_db()
    duplicate_link.refresh_from_db()
    assert selected_link.status == ParticipantBookingLink.Status.ACCEPTED
    assert duplicate_link.status == ParticipantBookingLink.Status.REVOKED


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
    page_response = kiosk_client.get(reverse("kiosk-home"))
    partner_child_token = f"family-{partner_child.pk}"
    state_token = next(
        target["state_token"]
        for target in page_response.context["checkin_participants"]
        if target["token"] == partner_child_token
    )

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [partner_child_token],
            f"arrival_date_{partner_child_token}": "2026-07-03",
            f"departure_date_{partner_child_token}": "2026-07-09",
            f"checkin_state_{partner_child_token}": state_token,
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
def test_multi_partner_checkin_locks_authorizations_in_canonical_order(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(
        is_active=True,
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 14),
    )
    participant = ParticipantFactory(camp=camp)
    first_partner = ParticipantFactory(camp=camp)
    second_partner = ParticipantFactory(camp=camp)
    second_link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=second_partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    first_link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=first_partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    page_response = kiosk_client.get(reverse("kiosk-home"))
    checkin_targets = {target["token"]: target for target in page_response.context["checkin_participants"]}
    first_token = f"participant-{first_partner.pk}"
    second_token = f"participant-{second_partner.pk}"
    lock_events = []
    original_fetch_all = QuerySet._fetch_all

    def capture_lock_event(queryset):
        was_unfetched = queryset._result_cache is None
        original_fetch_all(queryset)
        if (
            was_unfetched
            and queryset.query.select_for_update
            and queryset.model in {Participant, ParticipantBookingLink}
        ):
            lock_events.append(
                (
                    queryset.model,
                    tuple(instance.pk for instance in queryset._result_cache),
                )
            )

    monkeypatch.setattr(QuerySet, "_fetch_all", capture_lock_event)

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [first_token, second_token],
            f"arrival_date_{first_token}": "2026-07-03",
            f"departure_date_{first_token}": "2026-07-09",
            f"checkin_state_{first_token}": checkin_targets[first_token]["state_token"],
            f"arrival_date_{second_token}": "2026-07-04",
            f"departure_date_{second_token}": "2026-07-10",
            f"checkin_state_{second_token}": checkin_targets[second_token]["state_token"],
        },
    )

    assert response.status_code == 302
    assert lock_events == [
        (Participant, tuple(sorted((participant.pk, first_partner.pk, second_partner.pk)))),
        (ParticipantBookingLink, tuple(sorted((first_link.pk, second_link.pk)))),
    ]


@pytest.mark.django_db
def test_stale_checkin_form_does_not_overwrite_unchanged_partner_row(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(
        is_active=True,
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 14),
    )
    participant = ParticipantFactory(camp=camp)
    partner = ParticipantFactory(camp=camp)
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    page_response = kiosk_client.get(reverse("kiosk-home"))
    checkin_targets = {target["token"]: target for target in page_response.context["checkin_participants"]}
    participant_token = f"participant-{participant.pk}"
    partner_token = f"participant-{partner.pk}"

    partner.arrival_date = date(2026, 7, 3)
    partner.departure_date = date(2026, 7, 9)
    partner.booked_nights = 6
    partner.save(update_fields=["arrival_date", "departure_date", "booked_nights", "updated_at"])
    partner_updated_at = partner.updated_at

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [participant_token, partner_token],
            f"arrival_date_{participant_token}": "2026-07-02",
            f"departure_date_{participant_token}": "2026-07-10",
            f"checkin_state_{participant_token}": checkin_targets[participant_token]["state_token"],
            f"arrival_date_{partner_token}": "",
            f"departure_date_{partner_token}": "",
            f"checkin_state_{partner_token}": checkin_targets[partner_token]["state_token"],
        },
    )

    participant.refresh_from_db()
    partner.refresh_from_db()
    assert response.status_code == 302
    assert participant.arrival_date == date(2026, 7, 2)
    assert participant.departure_date == date(2026, 7, 10)
    assert partner.arrival_date == date(2026, 7, 3)
    assert partner.departure_date == date(2026, 7, 9)
    assert partner.booked_nights == 6
    assert partner.updated_at == partner_updated_at
    assert not KioskActionAuditLog.objects.exists()


@pytest.mark.django_db
def test_stale_dirty_checkin_row_rejects_entire_update(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(
        is_active=True,
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 14),
    )
    participant = ParticipantFactory(camp=camp)
    partner = ParticipantFactory(camp=camp)
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    page_response = kiosk_client.get(reverse("kiosk-home"))
    checkin_targets = {target["token"]: target for target in page_response.context["checkin_participants"]}
    participant_token = f"participant-{participant.pk}"
    partner_token = f"participant-{partner.pk}"

    partner.arrival_date = date(2026, 7, 3)
    partner.departure_date = date(2026, 7, 9)
    partner.booked_nights = 6
    partner.save(update_fields=["arrival_date", "departure_date", "booked_nights", "updated_at"])

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [participant_token, partner_token],
            f"arrival_date_{participant_token}": "2026-07-02",
            f"departure_date_{participant_token}": "2026-07-10",
            f"checkin_state_{participant_token}": checkin_targets[participant_token]["state_token"],
            f"arrival_date_{partner_token}": "2026-07-04",
            f"departure_date_{partner_token}": "2026-07-08",
            f"checkin_state_{partner_token}": checkin_targets[partner_token]["state_token"],
        },
    )

    participant.refresh_from_db()
    partner.refresh_from_db()
    assert response.status_code == 200
    assert participant.arrival_date is None
    assert participant.departure_date is None
    assert partner.arrival_date == date(2026, 7, 3)
    assert partner.departure_date == date(2026, 7, 9)
    assert partner.booked_nights == 6
    assert "Die Check-in-Daten wurden zwischenzeitlich geändert." in response.content.decode("utf-8")
    assert not KioskActionAuditLog.objects.exists()


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
def test_partner_meal_retraction_revalidates_stale_state_after_row_lock(
    kiosk_client,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
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
    ParticipantBookingLink.objects.create(
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
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    page_response = kiosk_client.get(reverse("kiosk-home"))
    visible_signup = next(item for item in page_response.context["meal_signups"] if item.pk == signup.pk)
    confirmation_token = visible_signup.retraction_confirmation_token

    with django_capture_on_commit_callbacks() as notification_callbacks:
        with transaction.atomic():
            first_result = _retract_meal_signup(
                signup,
                participant,
                confirmation_token=confirmation_token,
            )
        with transaction.atomic():
            stale_result = _retract_meal_signup(
                signup,
                participant,
                confirmation_token=confirmation_token,
            )

    assert first_result is True
    assert stale_result is False
    assert KioskActionAuditLog.objects.filter(action=KioskActionAuditLog.Action.MEAL_RETRACTED).count() == 1
    assert len(notification_callbacks) == 1


@pytest.mark.django_db
def test_partner_meal_retraction_confirmation_cannot_be_replayed_after_rebooking():
    actor = ParticipantFactory()
    partner = ParticipantFactory(camp=actor.camp)
    ParticipantBookingLink.objects.create(
        inviter=actor,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    price_rule = PriceRuleFactory(
        camp=actor.camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        unit_price=Decimal("8.00"),
    )
    target = {
        "kind": "participant",
        "object": partner,
    }
    meal_date = date(2026, 7, 2)

    with transaction.atomic():
        _book_meal_for_target(
            target,
            meal_date,
            MealSignup.Meal.DINNER,
            MealSignup.Variant.NORMAL,
            price_rule,
            actor,
        )
    signup = MealSignup.objects.select_related("charge").get(participant=partner)
    stale_confirmation_token = _sign_kiosk_meal_retraction(actor, signup)

    with transaction.atomic():
        assert (
            _retract_meal_signup(
                signup,
                actor,
                confirmation_token=stale_confirmation_token,
            )
            is True
        )
    with transaction.atomic():
        _book_meal_for_target(
            target,
            meal_date,
            MealSignup.Meal.DINNER,
            MealSignup.Variant.NORMAL,
            price_rule,
            actor,
        )
    signup.refresh_from_db()
    signup.charge.refresh_from_db()
    assert signup.status == MealSignup.Status.ACTIVE
    assert signup.charge.deleted_at is None

    with transaction.atomic():
        stale_result = _retract_meal_signup(
            signup,
            actor,
            confirmation_token=stale_confirmation_token,
        )

    signup.refresh_from_db()
    signup.charge.refresh_from_db()
    assert stale_result is False
    assert signup.status == MealSignup.Status.ACTIVE
    assert signup.charge.deleted_at is None

    current_confirmation_token = _sign_kiosk_meal_retraction(actor, signup)
    with transaction.atomic():
        current_result = _retract_meal_signup(
            signup,
            actor,
            confirmation_token=current_confirmation_token,
        )
    assert current_result is True


@pytest.mark.django_db
def test_meal_signup_row_locks_exclude_nullable_postgresql_joins(monkeypatch):
    participant = ParticipantFactory()
    price_rule = PriceRuleFactory(
        camp=participant.camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
    )
    postgresql_settings = django_settings.DATABASES["default"].copy()
    postgresql_settings.update(
        {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "compile_only",
        }
    )
    postgresql_connection = DatabaseWrapper(postgresql_settings, alias="postgresql_compile")
    monkeypatch.setattr(postgresql_connection, "get_autocommit", lambda: False)
    locked_meal_signup_sql: list[str] = []
    original_first = QuerySet.first

    def capture_locked_meal_signup_sql(queryset):
        if queryset.model is MealSignup and queryset.query.select_for_update:
            sql, _params = queryset.query.get_compiler(connection=postgresql_connection).as_sql()
            locked_meal_signup_sql.append(sql)
        return original_first(queryset)

    monkeypatch.setattr(QuerySet, "first", capture_locked_meal_signup_sql)
    target = {
        "kind": "participant",
        "object": participant,
    }

    with transaction.atomic():
        _book_meal_for_target(
            target,
            date(2026, 7, 2),
            MealSignup.Meal.DINNER,
            MealSignup.Variant.NORMAL,
            price_rule,
            participant,
        )
    signup = MealSignup.objects.get(participant=participant)
    with transaction.atomic():
        retracted = _retract_meal_signup(signup, participant)

    assert retracted is True
    assert len(locked_meal_signup_sql) == 2
    assert all(" LEFT OUTER JOIN " in sql for sql in locked_meal_signup_sql)
    assert all(' FOR UPDATE OF "billing_mealsignup"' in sql for sql in locked_meal_signup_sql)


@pytest.mark.django_db
def test_partner_meal_workflows_lock_signup_before_authorization(monkeypatch):
    actor = ParticipantFactory()
    partner = ParticipantFactory(camp=actor.camp)
    ParticipantBookingLink.objects.create(
        inviter=actor,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    price_rule = PriceRuleFactory(
        camp=actor.camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
    )
    target = {
        "kind": "participant",
        "object": partner,
    }
    lock_order_by_workflow = {
        "book": [],
        "retract": [],
    }
    active_workflow = "book"
    original_fetch_all = QuerySet._fetch_all

    def capture_lock_order(queryset):
        was_unfetched = queryset._result_cache is None
        original_fetch_all(queryset)
        if (
            was_unfetched
            and queryset.query.select_for_update
            and queryset.model
            in {
                MealSignup,
                Participant,
                ParticipantBookingLink,
            }
        ):
            lock_order_by_workflow[active_workflow].append(queryset.model)

    monkeypatch.setattr(QuerySet, "_fetch_all", capture_lock_order)

    with transaction.atomic():
        _book_meal_for_target(
            target,
            date(2026, 7, 2),
            MealSignup.Meal.DINNER,
            MealSignup.Variant.NORMAL,
            price_rule,
            actor,
        )
    signup = MealSignup.objects.select_related("charge").get(participant=partner)
    confirmation_token = _sign_kiosk_meal_retraction(actor, signup)

    active_workflow = "retract"
    with transaction.atomic():
        retracted = _retract_meal_signup(
            signup,
            actor,
            confirmation_token=confirmation_token,
        )

    assert retracted is True
    assert lock_order_by_workflow == {
        "book": [MealSignup, Participant, ParticipantBookingLink],
        "retract": [MealSignup, Participant, ParticipantBookingLink],
    }


@pytest.mark.django_db
def test_partner_meal_batch_locks_all_signups_before_authorization(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 6, 30, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(
        is_active=True,
        starts_on=date(2026, 6, 30),
        ends_on=date(2026, 7, 14),
    )
    actor = ParticipantFactory(camp=camp)
    first_partner = ParticipantFactory(camp=camp)
    second_partner = ParticipantFactory(camp=camp)
    first_link = ParticipantBookingLink.objects.create(
        inviter=actor,
        invitee=first_partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    second_link = ParticipantBookingLink.objects.create(
        inviter=actor,
        invitee=second_partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        applies_to_adults=True,
        is_default=True,
        unit_price=Decimal("8.00"),
    )
    signups = [
        MealSignup.objects.create(
            participant=partner,
            meal_date=meal_date,
            meal=MealSignup.Meal.DINNER,
            variant=MealSignup.Variant.NORMAL,
        )
        for partner in (first_partner, second_partner)
        for meal_date in (date(2026, 7, 2), date(2026, 7, 3))
    ]
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = actor.pk
    session.save()
    lock_events = []
    original_fetch_all = QuerySet._fetch_all

    def capture_lock_event(queryset):
        was_unfetched = queryset._result_cache is None
        original_fetch_all(queryset)
        if (
            was_unfetched
            and queryset.query.select_for_update
            and queryset.model in {MealSignup, Participant, ParticipantBookingLink}
        ):
            lock_events.append(
                (
                    queryset.model,
                    tuple(instance.pk for instance in queryset._result_cache),
                )
            )

    monkeypatch.setattr(QuerySet, "_fetch_all", capture_lock_event)

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": ["2026-07-02", "2026-07-03"],
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
            "meal-target": [
                f"participant-{second_partner.pk}",
                f"participant-{first_partner.pk}",
            ],
            f"meal-variant-participant-{first_partner.pk}": MealSignup.Variant.NORMAL,
            f"meal-variant-participant-{second_partner.pk}": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 302
    first_authorization_lock = next(
        index for index, (model, _pks) in enumerate(lock_events) if model is ParticipantBookingLink
    )
    locked_signup_ids = {
        pk for model, pks in lock_events[:first_authorization_lock] if model is MealSignup for pk in pks
    }
    assert locked_signup_ids == {signup.pk for signup in signups}
    assert all(model is not MealSignup for model, _pks in lock_events[first_authorization_lock:])
    participant_locks = [pks for model, pks in lock_events if model is Participant]
    assert participant_locks == [tuple(sorted((actor.pk, first_partner.pk, second_partner.pk)))]
    authorization_locks = [pks for model, pks in lock_events if model is ParticipantBookingLink]
    assert authorization_locks == [tuple(sorted((first_link.pk, second_link.pk)))]


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
def test_multi_partner_quick_booking_locks_authorizations_in_canonical_order(kiosk_client, monkeypatch):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp, is_child=False, is_companion=False)
    first_partner = ParticipantFactory(camp=camp, is_child=False, is_companion=False)
    second_partner = ParticipantFactory(camp=camp, is_child=False, is_companion=False)
    first_partner_child = ParticipantFamilyMember.objects.create(
        guardian=first_partner,
        first_name="Kind",
        last_name="Partner",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    first_link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=first_partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    second_link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=second_partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    rule = PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        unit_price=Decimal("2.00"),
        applies_to_children=True,
        applies_to_adults=True,
        applies_to_companions=False,
    )
    target_tokens = [
        f"participant-{second_partner.pk}",
        f"family-{first_partner_child.pk}",
    ]
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    request_data = {
        "action": "quick",
        "quick-price_rule": rule.pk,
        "quick-quantity": 1,
        "quick-targets-submitted": "1",
        "quick-target": target_tokens,
    }
    preview_response = kiosk_client.post(reverse("kiosk-home"), request_data)
    confirmation = preview_response.context["quick_confirmation"]
    lock_events = []
    original_fetch_all = QuerySet._fetch_all

    def capture_lock_event(queryset):
        was_unfetched = queryset._result_cache is None
        original_fetch_all(queryset)
        if (
            was_unfetched
            and queryset.query.select_for_update
            and queryset.model in {Participant, ParticipantFamilyMember, ParticipantBookingLink}
        ):
            lock_events.append(
                (
                    queryset.model,
                    tuple(instance.pk for instance in queryset._result_cache),
                )
            )

    monkeypatch.setattr(QuerySet, "_fetch_all", capture_lock_event)

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            **request_data,
            "quick-confirmed": "1",
            "quick-confirmation-token": confirmation["token"],
        },
    )

    assert preview_response.status_code == 200
    assert response.status_code == 302
    assert Charge.objects.count() == 2
    assert lock_events == [
        (Participant, tuple(sorted((participant.pk, first_partner.pk, second_partner.pk)))),
        (ParticipantFamilyMember, (first_partner_child.pk,)),
        (ParticipantBookingLink, tuple(sorted((first_link.pk, second_link.pk)))),
    ]


@pytest.mark.django_db
def test_partner_quick_cancellation_locks_dependencies_before_authorization(kiosk_client, monkeypatch):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)
    partner = ParticipantFactory(camp=camp)
    partner_child = ParticipantFamilyMember.objects.create(
        guardian=partner,
        first_name="Kind",
        last_name="Partner",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    booking_link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    charge = Charge.objects.create(
        participant=partner,
        kiosk_booked_by=partner,
        kind=Charge.Kind.DRINK,
        description="Wasser (Kiosk) für Kind Partner",
        quantity=Decimal("1.00"),
        unit_price=Decimal("1.50"),
    )
    KioskActionAuditLog.objects.create(
        camp=camp,
        actor_participant=partner,
        target_participant=partner,
        target_family_member=partner_child,
        booking_link=booking_link,
        charge=charge,
        action=KioskActionAuditLog.Action.QUICK_BOOKED,
        description=f"{charge.booking_reference}: Schnellbuchung erstellt.",
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    lock_events = []
    original_fetch_all = QuerySet._fetch_all

    def capture_lock_event(queryset):
        was_unfetched = queryset._result_cache is None
        original_fetch_all(queryset)
        if (
            was_unfetched
            and queryset.query.select_for_update
            and queryset.model in {Participant, ParticipantFamilyMember, ParticipantBookingLink}
        ):
            lock_events.append(
                (
                    queryset.model,
                    tuple(instance.pk for instance in queryset._result_cache),
                )
            )

    monkeypatch.setattr(QuerySet, "_fetch_all", capture_lock_event)

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "quick_cancel",
            "charge_id": charge.pk,
        },
    )

    assert response.status_code == 302
    assert lock_events == [
        (Participant, tuple(sorted((participant.pk, partner.pk)))),
        (ParticipantFamilyMember, (partner_child.pk,)),
        (ParticipantBookingLink, (booking_link.pk,)),
    ]


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
def test_revoke_closes_every_active_authorization_for_the_partner_pair(kiosk_client):
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
    stale_pending_link = ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=partner,
        status=ParticipantBookingLink.Status.PENDING,
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
    stale_pending_link.refresh_from_db()
    assert selected_link.status == ParticipantBookingLink.Status.REVOKED
    assert duplicate_link.status == ParticipantBookingLink.Status.REVOKED
    assert stale_pending_link.status == ParticipantBookingLink.Status.REVOKED
    assert kiosk_client.get(reverse("kiosk-participant-current-settlement-pdf", args=[partner.pk])).status_code == 403
