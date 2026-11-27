from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection
from django.urls import reverse

from billing.feature_controls import FEATURE_LABELS, feature_enabled
from billing.forms import CampForm
from billing.models import (
    CampFeatureOverride,
    Charge,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    PriceRule,
    PushMessage,
    PushSubscription,
)
from billing.notifications import queue_account_recovery_push, queue_participant_notification, send_due_push_messages
from tests.factories import CampFactory, ParticipantFactory, SuperUserFactory, UserFactory
from tests.kiosk_helpers import authenticate_kiosk_session

attribute_queued_participant_messages = import_module(
    "billing.migrations.0083_camp_feature_controls"
).attribute_queued_participant_messages


def _camp_form_data(camp, *, disabled=(), include_feature_fields=True):
    data = {
        "name": camp.name,
        "year": str(camp.year),
        "starts_on": camp.starts_on.isoformat() if camp.starts_on else "",
        "ends_on": camp.ends_on.isoformat() if camp.ends_on else "",
        "is_active": "on" if camp.is_active else "",
        "meal_booking_cutoff_time": camp.meal_booking_cutoff_time.strftime("%H:%M"),
        "shift_ratio_per_night": str(camp.shift_ratio_per_night),
        "iban": camp.iban,
        "paypal_link": camp.paypal_link,
        "notes": camp.notes,
        "show_kiosk_invoices": "on" if camp.show_kiosk_invoices else "",
    }
    if include_feature_fields:
        for feature_id in FEATURE_LABELS:
            data[f"feature_present_{feature_id}"] = "1"
            if feature_id not in disabled:
                data[f"feature_{feature_id}"] = "on"
    return data


def _authenticate(client, participant):
    session = client.session
    authenticate_kiosk_session(session, participant)
    session.save()


@pytest.mark.django_db
def test_known_features_default_on_and_unknown_features_fail_closed():
    camp = CampFactory()

    assert all(feature_enabled(camp, feature_id) for feature_id in FEATURE_LABELS)
    assert not feature_enabled(camp, "typo")

    CampFeatureOverride.objects.create(camp=camp, feature_id="meals", enabled=False)
    assert not feature_enabled(camp, "meals")
    with pytest.raises(ValidationError, match="Unbekannte Lagerfunktion"):
        CampFeatureOverride(camp=camp, feature_id="typo", enabled=True).full_clean()


@pytest.mark.django_db
def test_legacy_camp_form_post_keeps_feature_defaults_and_existing_invoice_preorder_flags():
    camp = CampFactory(show_kiosk_invoices=False, allow_breakfast_prebooking_before_camp=False)
    form = CampForm(instance=camp, data=_camp_form_data(camp, include_feature_fields=False))

    assert form.is_valid(), form.errors
    saved = form.save()

    assert saved.show_kiosk_invoices is False
    assert saved.allow_breakfast_prebooking_before_camp is False
    assert all(feature_enabled(saved, feature_id) for feature_id in FEATURE_LABELS)


@pytest.mark.django_db
def test_admin_camp_edit_persists_feature_checkbox_after_rendered_form(client):
    admin = SuperUserFactory()
    camp = CampFactory(show_kiosk_invoices=False, allow_breakfast_prebooking_before_camp=False)
    client.force_login(admin)
    url = reverse("camp-edit", kwargs={"camp_id": camp.pk})

    rendered = client.get(url)
    assert rendered.status_code == 200
    assert b"Optionale Benachrichtigungen" in rendered.content
    response = client.post(url, _camp_form_data(camp, disabled={"meals"}))

    assert response.status_code == 302
    assert not feature_enabled(camp, "meals")
    camp.refresh_from_db()
    assert camp.show_kiosk_invoices is False
    assert camp.allow_breakfast_prebooking_before_camp is False


@pytest.mark.django_db
@pytest.mark.parametrize("disabled_feature", ["shifts", "notifications"])
def test_disabling_a_feature_terminally_suppresses_queued_messages_even_after_reenable(settings, disabled_feature):
    settings.WEB_PUSH_ENABLED = True
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    subscription = PushSubscription.objects.create(
        participant=participant,
        endpoint="https://push.example.test/feature-controls",
        p256dh="public-key",
        auth="auth-key",
        categories=["shifts"],
    )

    assert (
        queue_participant_notification(
            participant,
            category="shifts",
            title="Schicht",
            body="Erinnerung",
            target_url="/kiosk/shifts/",
            dedupe_key="feature-control-test",
        )
        == 1
    )
    message = PushMessage.objects.get(subscription=subscription)
    assert message.feature_id == "shifts"
    assert message.camp_id == camp.pk

    disable_form = CampForm(instance=camp, data=_camp_form_data(camp, disabled={disabled_feature}))
    assert disable_form.is_valid(), disable_form.errors
    disable_form.save()
    message.refresh_from_db()
    assert message.status == PushMessage.Status.FAILED
    assert message.last_error_code == "feature_disabled"
    assert (
        queue_participant_notification(
            participant,
            category="shifts",
            title="Schicht",
            body="Erinnerung",
            target_url="/kiosk/shifts/",
            dedupe_key="disabled-queue-attempt",
        )
        == 0
    )

    camp.refresh_from_db()
    enable_form = CampForm(instance=camp, data=_camp_form_data(camp))
    assert enable_form.is_valid(), enable_form.errors
    enable_form.save()
    assert (
        queue_participant_notification(
            participant,
            category="shifts",
            title="Schicht",
            body="Erinnerung",
            target_url="/kiosk/shifts/",
            dedupe_key="feature-control-test",
        )
        == 0
    )
    with patch("billing.notifications.webpush") as webpush:
        send_due_push_messages()
    webpush.assert_not_called()
    message.refresh_from_db()
    assert message.status == PushMessage.Status.FAILED


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "action", "feature_id"),
    [
        ("kiosk-shifts", "get", "shifts"),
        ("central-kiosk-shifts", "get", "shifts"),
        ("kiosk-shared-expense-request", "get", "expenses"),
        ("central-kiosk-shared-expense-request", "get", "expenses"),
    ],
)
def test_disabled_kiosk_routes_reject_direct_get_for_both_modes(kiosk_client, route_name, action, feature_id):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    _authenticate(kiosk_client, participant)
    CampFeatureOverride.objects.create(camp=camp, feature_id=feature_id, enabled=False)

    response = kiosk_client.get(reverse(route_name))

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["kiosk-home", "central-kiosk-home"])
def test_disabled_donation_rejects_direct_post_without_creating_charge(kiosk_client, route_name):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    _authenticate(kiosk_client, participant)
    CampFeatureOverride.objects.create(camp=camp, feature_id="donations", enabled=False)

    response = kiosk_client.post(reverse(route_name), {"action": "donate", "donation_amount": "20"})

    assert response.status_code == 403
    assert not Charge.objects.filter(participant=participant, kind=Charge.Kind.DONATION).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["kiosk-profile", "central-kiosk-profile"])
def test_disabled_profile_remains_readable_but_rejects_direct_post(kiosk_client, route_name):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, email="old@example.test")
    _authenticate(kiosk_client, participant)
    CampFeatureOverride.objects.create(camp=camp, feature_id="profile", enabled=False)
    url = reverse(route_name, kwargs={"participant_id": participant.pk})

    response = kiosk_client.get(url)
    assert response.status_code == 200
    assert b"disabled" in response.content

    response = kiosk_client.post(url, {"first_name": "Changed", "last_name": participant.last_name})
    participant.refresh_from_db()
    assert response.status_code == 403
    assert participant.first_name != "Changed"


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["kiosk-self-register", "central-kiosk-self-register"])
def test_disabled_self_registration_rejects_direct_post(kiosk_client, route_name):
    camp = CampFactory()
    CampFeatureOverride.objects.create(camp=camp, feature_id="self_registration", enabled=False)

    response = kiosk_client.post(reverse(route_name), {})

    assert response.status_code == 403
    assert not Participant.objects.filter(camp=camp, status=Participant.Status.PENDING_APPROVAL).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["kiosk-home", "central-kiosk-home"])
def test_render_then_disable_hides_user_actions_but_keeps_read_history_and_denies_posts(kiosk_client, route_name):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    _authenticate(kiosk_client, participant)
    enabled_response = kiosk_client.get(reverse(route_name))
    assert enabled_response.status_code == 200
    assert enabled_response.context["kiosk_features"]["meals"] is True
    assert b'data-kiosk-card="food"' in enabled_response.content
    assert b'data-kiosk-card="drinks"' in enabled_response.content
    Charge.objects.create(
        participant=participant,
        kiosk_booked_by=participant,
        kind=Charge.Kind.DRINK,
        description="Historisches Getränk",
        quantity=1,
        unit_price="1.00",
    )

    disable_form = CampForm(
        instance=camp,
        data=_camp_form_data(camp, disabled={"meals", "drinks", "attendance", "donations"}),
    )
    assert disable_form.is_valid(), disable_form.errors
    disable_form.save()

    disabled_response = kiosk_client.get(reverse(route_name))
    assert disabled_response.status_code == 200
    assert b'data-kiosk-card="food"' not in disabled_response.content
    assert b'data-kiosk-card="drinks"' not in disabled_response.content
    assert "Historisches Getränk".encode() in disabled_response.content
    assert disabled_response.context["kiosk_features"]["meals"] is False

    meal_post = kiosk_client.post(reverse(route_name), {"action": "meal"})
    assert meal_post.status_code == 403
    drink_rule = PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        name="Wasser",
        unit_price="1.00",
    )
    drink_post = kiosk_client.post(
        reverse(route_name),
        {"action": "quick", "quick-price_rule": drink_rule.pk},
    )
    assert drink_post.status_code == 403
    attendance_post = kiosk_client.post(reverse(route_name), {"action": "checkin"})
    assert attendance_post.status_code == 403
    donation_post = kiosk_client.post(reverse(route_name), {"action": "donate", "donation_amount": "5"})
    assert donation_post.status_code == 403
    assert Charge.objects.filter(participant=participant).count() == 1
    enable_form = CampForm(instance=camp, data=_camp_form_data(camp))
    assert enable_form.is_valid(), enable_form.errors
    enable_form.save()
    enabled_response = kiosk_client.get(reverse(route_name))
    assert enabled_response.context["kiosk_features"]["meals"] is True
    assert b'data-kiosk-card="food"' in enabled_response.content
    donation_post = kiosk_client.post(reverse(route_name), {"action": "donate", "donation_amount": "5"})
    assert donation_post.status_code == 302
    assert Charge.objects.filter(participant=participant, kind=Charge.Kind.DONATION).exists()


@pytest.mark.django_db
def test_family_toggle_blocks_changes_but_preserves_family_profile_reads(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    family_member = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Kind",
        last_name="Muster",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    _authenticate(kiosk_client, participant)
    CampFeatureOverride.objects.create(camp=camp, feature_id="family", enabled=False)

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "family_member_create"})
    assert response.status_code == 403
    profile_url = reverse("kiosk-family-member-profile", kwargs={"family_member_id": family_member.pk})
    assert kiosk_client.get(profile_url).status_code == 200
    assert kiosk_client.post(profile_url, {"first_name": "Changed", "last_name": "Muster"}).status_code == 403
    family_member.refresh_from_db()
    assert family_member.first_name == "Kind"


@pytest.mark.django_db
def test_partner_toggle_blocks_new_or_accepted_links_but_keeps_decline_and_revoke(kiosk_client):
    camp = CampFactory()
    inviter = ParticipantFactory(camp=camp)
    invitee = ParticipantFactory(camp=camp)
    pending = ParticipantBookingLink.objects.create(inviter=inviter, invitee=invitee)
    _authenticate(kiosk_client, inviter)
    CampFeatureOverride.objects.create(camp=camp, feature_id="partners", enabled=False)

    assert (
        kiosk_client.post(
            reverse("kiosk-partner-activity"),
            {"action": "booking_link_invite", "link-participant": invitee.pk},
        ).status_code
        == 403
    )
    assert (
        kiosk_client.post(
            reverse("kiosk-partner-activity"),
            {"action": "booking_link_accept", "booking_link_id": pending.pk},
        ).status_code
        == 403
    )

    _authenticate(kiosk_client, invitee)
    decline = kiosk_client.post(
        reverse("kiosk-partner-activity"),
        {"action": "booking_link_decline", "booking_link_id": pending.pk},
    )
    assert decline.status_code == 302
    pending.refresh_from_db()
    assert pending.status == ParticipantBookingLink.Status.DECLINED

    accepted = ParticipantBookingLink.objects.create(
        inviter=inviter,
        invitee=invitee,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    _authenticate(kiosk_client, inviter)
    revoke = kiosk_client.post(
        reverse("kiosk-partner-activity"),
        {"action": "booking_link_revoke", "booking_link_id": accepted.pk},
    )
    assert revoke.status_code == 302
    accepted.refresh_from_db()
    assert accepted.status == ParticipantBookingLink.Status.REVOKED


@pytest.mark.django_db
def test_feature_state_is_isolated_between_camps():
    first = CampFactory()
    second = CampFactory(name="Second Camp", is_active=False)
    CampFeatureOverride.objects.create(camp=first, feature_id="meals", enabled=False)

    assert not feature_enabled(first, "meals")
    assert feature_enabled(second, "meals")


@pytest.mark.django_db
def test_migration_attributes_participant_pushes_and_fails_unattributed_optional_messages():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    participant_subscription = PushSubscription.objects.create(
        participant=participant,
        endpoint="https://push.example.test/migration-participant",
        p256dh="public-key",
        auth="auth-key",
        categories=["shifts"],
    )
    participant_message = PushMessage.objects.create(
        subscription=participant_subscription,
        category="shifts",
        title="Dienst",
        body="Erinnerung",
        target_url="/kiosk/shifts/",
        dedupe_key="legacy-participant",
    )
    user = UserFactory()
    admin_subscription = PushSubscription.objects.create(
        user=user,
        endpoint="https://push.example.test/migration-unattributed",
        p256dh="public-key",
        auth="auth-key",
        categories=["meal_deadlines"],
    )
    unattributed_message = PushMessage.objects.create(
        subscription=admin_subscription,
        category="meal_deadlines",
        title="Essen",
        body="Prüfen",
        target_url="/kiosk/#meal-calendar",
        dedupe_key="legacy-unattributed",
    )

    attribute_queued_participant_messages(apps, SimpleNamespace(connection=connection))

    participant_message.refresh_from_db()
    unattributed_message.refresh_from_db()
    assert participant_message.camp_id == camp.pk
    assert participant_message.feature_id == "shifts"
    assert participant_message.status == PushMessage.Status.PENDING
    assert unattributed_message.status == PushMessage.Status.FAILED
    assert unattributed_message.last_error_code == "feature_unattributed"


@pytest.mark.django_db
def test_account_recovery_push_stays_available_when_optional_notifications_are_off(settings):
    settings.WEB_PUSH_ENABLED = True
    participant = ParticipantFactory()
    CampFeatureOverride.objects.create(camp=participant.camp, feature_id="notifications", enabled=False)
    subscription = PushSubscription.objects.create(
        participant=participant,
        endpoint="https://push.example.test/recovery-while-disabled",
        p256dh="public-key",
        auth="auth-key",
        categories=["security"],
        identity_verified=True,
    )

    queued = queue_account_recovery_push(
        participant,
        kind="participant_pin",
        title="PIN wiederherstellen",
        body="Sicherheitslink",
        target_url="/account-recovery/PLACEHOLDER/",
    )

    assert queued == 1
    message = PushMessage.objects.get(subscription=subscription)
    assert message.account_recovery_id is not None
    assert message.category == "account_security"
