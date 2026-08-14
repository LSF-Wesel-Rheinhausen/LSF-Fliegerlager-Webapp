from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import resolve, reverse
from django.utils import timezone

from billing.kiosk_access import (
    KIOSK_FAMILY_MEMBER_SESSION_KEY,
    KIOSK_PARTICIPANT_SESSION_KEY,
    KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY,
    KIOSK_PIN_SETUP_SESSION_KEY,
)
from billing.models import (
    Charge,
    Expense,
    KioskActionAuditLog,
    MealOrder,
    MealPlanEntry,
    MealSignup,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    Payment,
    PriceRule,
    Shift,
    ShiftAssignment,
    UserProfile,
)
from billing.services import create_settlement_run
from tests.factories import CampFactory, ExpenseFactory, ParticipantFactory, PriceRuleFactory, UserFactory


def _freeze_meal_lock_time(monkeypatch, fixed_now):
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    monkeypatch.setattr("billing.models.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())


def _checkin_state_tokens(kiosk_client):
    response = kiosk_client.get(reverse("kiosk-home"))
    return {target["token"]: target["state_token"] for target in response.context["checkin_participants"]}


@pytest.mark.django_db
def test_kiosk_user_guide_points_menu_only_sections_to_menu(kiosk_client):
    response = kiosk_client.get(reverse("user-guide"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Menü → Letzte Schnellbuchungen" in content
    assert "Abendessen (Kalender)" in content
    assert "Menü → Familie" in content
    assert "Menü → Partner &amp; Aktivitäten" in content
    assert "gegenseitige Partner-Vollmacht" in content
    assert "Abrechnung und PDF" in content
    assert "Anreise und Abreise" in content
    assert "aktive Begleitpersonen beider Hauptkonten" in content
    assert "mit ihrer eigenen PIN ausüben" in content
    assert "Menü → Eigene PIN ändern" in content
    assert "strikt getrennt" not in content
    assert "scrolle auf der Startseite" not in content
    for animation in ("login", "drinks", "meals", "family", "shifts"):
        assert f"/static/billing/docs/kiosk_{animation}.gif?v=2" in content


@pytest.mark.django_db
def test_kiosk_login_rejects_empty_participant_placeholder(kiosk_client):
    response = kiosk_client.post(reverse("kiosk-login"), {"participant": "", "pin": "1234"})

    assert response.status_code == 200
    assert "participant" in response.context["form"].errors
    assert KIOSK_PARTICIPANT_SESSION_KEY not in kiosk_client.session
    assert KIOSK_PIN_SETUP_SESSION_KEY not in kiosk_client.session


@pytest.mark.django_db
def test_kiosk_login_rejects_participant_without_preconfigured_pin(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")

    response = kiosk_client.post(
        reverse("kiosk-login"), {"participant": f"participant-{participant.pk}", "pin": "1234"}
    )

    assert response.status_code == 200
    assert b"Die PIN muss zuerst von der Lagerleitung gesetzt werden." in response.content
    assert KIOSK_PIN_SETUP_SESSION_KEY not in kiosk_client.session
    assert KIOSK_PARTICIPANT_SESSION_KEY not in kiosk_client.session


def test_kiosk_pin_setup_routes_are_not_exposed():
    assert resolve("/kiosk/pin/").url_name == "page-not-found"
    assert resolve("/central/kiosk/pin/").url_name == "page-not-found"


@pytest.mark.django_db
def test_kiosk_login_rejects_companion_without_preconfigured_pin(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )

    response = kiosk_client.post(reverse("kiosk-login"), {"participant": f"family-{companion.pk}", "pin": "1234"})

    assert response.status_code == 200
    assert b"Die PIN muss zuerst durch den zugeh\xc3\xb6rigen Teilnehmer gesetzt werden." in response.content
    assert KIOSK_PIN_SETUP_SESSION_KEY not in kiosk_client.session
    assert KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY not in kiosk_client.session
    assert KIOSK_PARTICIPANT_SESSION_KEY not in kiosk_client.session


@pytest.mark.django_db
def test_guardian_sets_pin_when_creating_companion(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_create",
            "family-first_name": "Grace",
            "family-last_name": "Hopper",
            "family-role": ParticipantFamilyMember.Role.COMPANION,
            "family-pin": "2468",
            "family-pin_repeat": "2468",
        },
    )

    assert response.status_code == 302
    companion = ParticipantFamilyMember.objects.get(guardian=participant, first_name="Grace")
    assert companion.pin.check_pin("2468") is True


@pytest.mark.django_db
def test_guardian_cannot_create_companion_without_pin(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_create",
            "family-first_name": "Grace",
            "family-last_name": "Hopper",
            "family-role": ParticipantFamilyMember.Role.COMPANION,
        },
    )

    assert response.status_code == 200
    assert b"Begleitpersonen ben\xc3\xb6tigen eine PIN." in response.content
    assert not ParticipantFamilyMember.objects.filter(guardian=participant, first_name="Grace").exists()


@pytest.mark.django_db
def test_kiosk_family_member_form_does_not_render_subsidy_controls(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    content = response.content.decode()
    assert response.status_code == 200
    assert 'name="family-is_youth_group"' not in content
    assert 'name="family-confirm_settlement_change"' not in content


@pytest.mark.django_db
@pytest.mark.parametrize("role", [ParticipantFamilyMember.Role.CHILD, ParticipantFamilyMember.Role.COMPANION])
def test_kiosk_family_member_creation_ignores_forged_subsidy_fields(kiosk_client, role):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    pin_data = {"family-pin": "2468", "family-pin_repeat": "2468"} if role == "companion" else {}

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_create",
            "family-first_name": "Grace",
            "family-last_name": "Hopper",
            "family-role": role,
            "family-is_youth_group": "on",
            "family-confirm_settlement_change": "on",
            **pin_data,
        },
    )

    assert response.status_code == 302
    member = ParticipantFamilyMember.objects.get(guardian=participant, first_name="Grace")
    assert member.role == role
    assert member.is_youth_group is False
    if role == ParticipantFamilyMember.Role.COMPANION:
        assert member.pin.check_pin("2468") is True


@pytest.mark.django_db
def test_guardian_can_set_pin_for_existing_companion(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_pin_set",
            "family_member_id": companion.pk,
            "family-pin": "8642",
            "family-pin_repeat": "8642",
        },
    )

    assert response.status_code == 302
    companion.pin.refresh_from_db()
    assert companion.pin.check_pin("8642") is True


@pytest.mark.django_db
def test_guardian_cannot_set_pin_for_another_participants_companion(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    other_participant = ParticipantFactory(camp=participant.camp, first_name="Alan", last_name="Turing")
    companion = ParticipantFamilyMember.objects.create(
        guardian=other_participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_pin_set",
            "family_member_id": companion.pk,
            "family-pin": "8642",
            "family-pin_repeat": "8642",
        },
    )

    assert response.status_code == 200
    assert b"Begleitperson wurde nicht gefunden." in response.content
    companion.pin.refresh_from_db()
    assert companion.pin.pin_hash == ""


@pytest.mark.django_db
def test_companion_cannot_set_pin_for_another_companion_of_same_guardian(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    authenticated_companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    target_companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Katherine",
        last_name="Johnson",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    target_companion.pin.set_pin("1357")
    target_companion.pin.save()
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = authenticated_companion.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_pin_set",
            "family_member_id": target_companion.pk,
            "family-pin": "8642",
            "family-pin_repeat": "8642",
        },
    )

    assert response.status_code == 403
    target_companion.pin.refresh_from_db()
    assert target_companion.pin.check_pin("1357") is True
    assert target_companion.pin.check_pin("8642") is False


@pytest.mark.django_db
def test_companion_cannot_create_another_companion_for_guardian(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    authenticated_companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = authenticated_companion.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_create",
            "family-first_name": "Katherine",
            "family-last_name": "Johnson",
            "family-role": ParticipantFamilyMember.Role.COMPANION,
            "family-pin": "8642",
            "family-pin_repeat": "8642",
        },
    )

    assert response.status_code == 403
    assert not ParticipantFamilyMember.objects.filter(
        guardian=participant,
        first_name="Katherine",
        last_name="Johnson",
    ).exists()


@pytest.mark.django_db
def test_kiosk_participant_can_change_own_pin_and_must_log_in_again(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    participant.pin.set_pin("2468")
    participant.pin.save()
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "pin_change",
            "pin-current_pin": "2468",
            "pin-pin": "8642",
            "pin-pin_repeat": "8642",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("kiosk-login")
    participant.pin.refresh_from_db()
    assert participant.pin.check_pin("8642") is True
    assert participant.pin.check_pin("2468") is False
    assert KIOSK_PARTICIPANT_SESSION_KEY not in kiosk_client.session
    assert KIOSK_FAMILY_MEMBER_SESSION_KEY not in kiosk_client.session


@pytest.mark.django_db
def test_kiosk_companion_can_change_only_own_pin(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    participant.pin.set_pin("9753")
    participant.pin.save()
    companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    companion.pin.set_pin("2468")
    companion.pin.save()
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = companion.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "pin_change",
            "pin-current_pin": "2468",
            "pin-pin": "8642",
            "pin-pin_repeat": "8642",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("kiosk-login")
    companion.pin.refresh_from_db()
    participant.pin.refresh_from_db()
    assert companion.pin.check_pin("8642") is True
    assert participant.pin.check_pin("9753") is True


@pytest.mark.django_db
def test_kiosk_pin_change_rejects_wrong_current_pin_and_counts_attempt(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    participant.pin.set_pin("2468")
    participant.pin.save()
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "pin_change",
            "pin-current_pin": "9999",
            "pin-pin": "8642",
            "pin-pin_repeat": "8642",
        },
    )

    assert response.status_code == 200
    assert "Die aktuelle PIN ist nicht korrekt." in response.content.decode("utf-8")
    assert b'id="pin-change-dialog" data-auto-open-dialog' in response.content
    participant.pin.refresh_from_db()
    assert participant.pin.failed_attempts == 1
    assert participant.pin.check_pin("2468") is True
    assert KIOSK_PARTICIPANT_SESSION_KEY in kiosk_client.session


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("new_pin", "pin_repeat", "error_text"),
    [
        ("1234", "1234", "sicherere PIN"),
        ("abcd", "abcd", "4 bis 10 Ziffern"),
        ("123", "123", "4 bis 10 Ziffern"),
        ("12345678901", "12345678901", "4 bis 10 Ziffern"),
        ("2468", "2468", "von der aktuellen PIN unterscheiden"),
        ("8642", "9753", "PINs stimmen nicht überein"),
    ],
)
def test_kiosk_pin_change_rejects_invalid_new_pin(kiosk_client, new_pin, pin_repeat, error_text):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    participant.pin.set_pin("2468")
    participant.pin.save()
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "pin_change",
            "pin-current_pin": "2468",
            "pin-pin": new_pin,
            "pin-pin_repeat": pin_repeat,
        },
    )

    assert response.status_code == 200
    assert error_text in response.content.decode("utf-8")
    participant.pin.refresh_from_db()
    assert participant.pin.check_pin("2468") is True
    assert KIOSK_PARTICIPANT_SESSION_KEY in kiosk_client.session


@pytest.mark.django_db
def test_kiosk_pin_change_is_available_after_camp(kiosk_client):
    camp = CampFactory(
        is_active=True,
        starts_on=timezone.localdate() - timedelta(days=2),
        ends_on=timezone.localdate() - timedelta(days=1),
    )
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    participant.pin.set_pin("2468")
    participant.pin.save()
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "pin_change",
            "pin-current_pin": "2468",
            "pin-pin": "8642",
            "pin-pin_repeat": "8642",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("kiosk-login")
    participant.pin.refresh_from_db()
    assert participant.pin.check_pin("8642") is True


@pytest.mark.django_db
def test_kiosk_home_renders_own_pin_change_dialog(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    participant.pin.set_pin("2468")
    participant.pin.save()
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"Eigene PIN \xc3\xa4ndern" in response.content
    assert b'id="pin-change-dialog"' in response.content
    assert b'name="pin-current_pin"' in response.content


@pytest.mark.django_db
def test_kiosk_pin_change_rejects_when_locked_out(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    participant.pin.set_pin("2468")
    participant.pin.failed_attempts = participant.pin.MAX_FAILED_ATTEMPTS
    participant.pin.locked_until = timezone.now() + timedelta(minutes=5)
    participant.pin.save()

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "pin_change",
            "pin-current_pin": "2468",
            "pin-pin": "8642",
            "pin-pin_repeat": "8642",
        },
    )

    assert response.status_code == 200
    assert "Zu viele Fehlversuche" in response.content.decode("utf-8")
    participant.pin.refresh_from_db()
    assert participant.pin.check_pin("8642") is False


@pytest.mark.django_db
def test_kiosk_pin_change_causes_lockout(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    participant.pin.set_pin("2468")
    participant.pin.save()

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    for _ in range(participant.pin.MAX_FAILED_ATTEMPTS):
        kiosk_client.post(
            reverse("kiosk-home"),
            {
                "action": "pin_change",
                "pin-current_pin": "9999",
                "pin-pin": "8642",
                "pin-pin_repeat": "8642",
            },
        )

    participant.pin.refresh_from_db()
    assert participant.pin.is_locked is True

    # Submitting with correct current_pin now still fails
    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "pin_change",
            "pin-current_pin": "2468",
            "pin-pin": "8642",
            "pin-pin_repeat": "8642",
        },
    )
    assert response.status_code == 200
    assert "Zu viele Fehlversuche" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_companion_cannot_deactivate_guardians_family_member(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    authenticated_companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    target_family_member = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Katherine",
        last_name="Johnson",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = authenticated_companion.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_deactivate",
            "family_member_id": target_family_member.pk,
        },
    )

    assert response.status_code == 403
    target_family_member.refresh_from_db()
    assert target_family_member.is_active is True


@pytest.mark.django_db
def test_companion_does_not_see_family_management(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    authenticated_companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Katherine",
        last_name="Johnson",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = authenticated_companion.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b'name="action" value="family_member_pin_set"' not in response.content
    assert b'name="action" value="family_member_create"' not in response.content
    assert b'name="action" value="family_member_deactivate"' not in response.content
    assert b'data-dialog-target="family-management-dialog"' not in response.content


@pytest.mark.django_db
def test_kiosk_login_accepts_companion_pin_and_uses_guardian_session(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    companion.pin.set_pin("1234")
    companion.pin.save()

    response = kiosk_client.post(reverse("kiosk-login"), {"participant": f"family-{companion.pk}", "pin": "1234"})

    assert response.status_code == 302
    assert response["Location"] == reverse("kiosk-home")
    assert kiosk_client.session[KIOSK_PARTICIPANT_SESSION_KEY] == participant.pk
    assert kiosk_client.session[KIOSK_FAMILY_MEMBER_SESSION_KEY] == companion.pk


@pytest.mark.django_db
def test_kiosk_login_rejects_invalid_pin_for_existing_pin(kiosk_client):
    participant = ParticipantFactory(first_name="Grace", last_name="Hopper")
    participant.pin.set_pin("1234")
    participant.pin.save()

    response = kiosk_client.post(
        reverse("kiosk-login"), {"participant": f"participant-{participant.pk}", "pin": "9999"}
    )

    assert response.status_code == 200
    assert KIOSK_PARTICIPANT_SESSION_KEY not in kiosk_client.session
    assert KIOSK_PIN_SETUP_SESSION_KEY not in kiosk_client.session
    assert b"Teilnehmer oder PIN ist ung\xc3\xbcltig." in response.content


@pytest.mark.django_db
def test_kiosk_login_locks_pin_after_repeated_failures(kiosk_client):
    participant = ParticipantFactory(first_name="Grace", last_name="Hopper")
    participant.pin.set_pin("1234")
    participant.pin.save()

    for _ in range(participant.pin.MAX_FAILED_ATTEMPTS):
        kiosk_client.post(reverse("kiosk-login"), {"participant": f"participant-{participant.pk}", "pin": "9999"})

    participant.pin.refresh_from_db()
    response = kiosk_client.post(
        reverse("kiosk-login"), {"participant": f"participant-{participant.pk}", "pin": "1234"}
    )

    assert participant.pin.is_locked is True
    assert response.status_code == 200
    assert b"Zu viele Fehlversuche" in response.content
    assert KIOSK_PARTICIPANT_SESSION_KEY not in kiosk_client.session


@pytest.mark.django_db
def test_kiosk_login_links_to_admin_interface(kiosk_client):
    response = kiosk_client.get(reverse("kiosk-login"))

    assert response.status_code == 200
    assert reverse("login").encode() in response.content
    assert b"Admin-Interface" in response.content
    content = response.content.decode()
    assert content.index("Teilnehmer auswählen") < content.index("Neu hier?")


@pytest.mark.django_db
def test_kiosk_home_hides_normal_admin_header_and_renders_drink_dialog_controls(kiosk_client):
    user = UserFactory(username="admin", email="admin@example.test")
    kiosk_client.force_login(user)

    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    for _ in range(2):
        Charge.objects.create(
            participant=participant,
            kind=Charge.Kind.DRINK,
            description="Apfelschorle",
            quantity=Decimal("1.00"),
            unit_price=Decimal("2.50"),
            occurred_on=date(2026, 7, 28),
        )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        name="Getränk",
        unit_price=Decimal("2.50"),
        is_default=True,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"admin@example.test" not in response.content
    assert b'action="/logout/"' not in response.content
    assert b'class="drink-card"' in response.content
    assert b'data-rule-id="' in response.content
    assert b'id="quick-dialog"' in response.content
    assert b'data-timeout-ms="120000"' not in response.content
    assert reverse("kiosk-logout").encode() in response.content
    assert "Förderung anwenden".encode() not in response.content
    assert b"Abrechnung ansehen" not in response.content
    assert "Details öffnen".encode() in response.content
    assert b'id="checkin-dialog"' in response.content
    assert b"data-open-checkin-dialog" in response.content
    assert b"data-open-kiosk-menu" in response.content
    assert b'id="kiosk-menu-dialog"' in response.content
    assert b"Brutto:" not in response.content
    assert b"Soll:" not in response.content
    assert b"28.07.2026" in response.content
    assert response.content.count(b"B#") >= 2


@pytest.mark.django_db
def test_pre_camp_kiosk_shows_only_identity_countdown_and_available_menu_areas(kiosk_client):
    camp = CampFactory(
        name="Leibertingen",
        year=2099,
        starts_on=date(2099, 7, 31),
        ends_on=date(2099, 8, 14),
    )
    inviter = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    ParticipantBookingLink.objects.create(
        inviter=inviter,
        invitee=participant,
        status=ParticipantBookingLink.Status.PENDING,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "data-pre-camp-overview" in content
    assert "Ada Lovelace" in content
    assert "bis Lagerbeginn" in content
    assert '<div class="kiosk-masonry" data-kiosk-masonry>' not in content
    assert "Aktuelle Abrechnung" not in content
    assert "Dein geplanter Anmeldezeitraum" not in content

    menu = content.split('<nav class="kiosk-menu" aria-label="Kiosk-Bereiche">', maxsplit=1)[1].split(
        "</nav>", maxsplit=1
    )[0]
    for available_area in ("Familie", "Partner &amp; Aktivitäten", "Hilfe", "Kontakt Lagerleitung"):
        assert available_area in menu
    for unavailable_area in (
        "Abendessen (Kalender)",
        "Letzte Schnellbuchungen",
        "Gemeinschaftsausgaben",
        "Benachrichtigungen",
    ):
        assert unavailable_area not in menu

    partner_response = kiosk_client.get(reverse("kiosk-partner-activity"))
    partner_content = partner_response.content.decode("utf-8")
    assert partner_response.status_code == 200
    assert "Grace Hopper" in partner_content
    assert 'value="booking_link_accept"' in partner_content
    assert 'value="booking_link_decline"' in partner_content


@pytest.mark.django_db
def test_pre_camp_kiosk_rejects_operational_posts(kiosk_client):
    camp = CampFactory(
        year=2099,
        starts_on=date(2099, 7, 31),
        ends_on=date(2099, 8, 14),
    )
    participant = ParticipantFactory(camp=camp)
    rule = PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        name="Wasser",
        unit_price=Decimal("1.50"),
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
        },
        follow=True,
    )

    assert response.status_code == 200
    assert "Diese Funktion ist erst ab Lagerbeginn verfügbar." in response.content.decode("utf-8")
    assert not Charge.objects.filter(participant=participant).exists()


@pytest.mark.django_db
def test_pre_camp_kiosk_login_uses_compact_layout(kiosk_client):
    CampFactory(
        year=2099,
        starts_on=date(2099, 7, 31),
        ends_on=date(2099, 8, 14),
    )

    response = kiosk_client.get(reverse("kiosk-login"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'class="kiosk-login-shell kiosk-login-shell--pre-camp"' in content
    assert "data-pre-camp-countdown" in content


@pytest.mark.django_db
def test_kiosk_checkin_targets_include_linked_household(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    linked = ParticipantFactory(camp=camp, first_name="Grace", last_name="B")
    linked_companion = ParticipantFamilyMember.objects.create(
        guardian=linked,
        first_name="Alan",
        last_name="B",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    linked_child = ParticipantFamilyMember.objects.create(
        guardian=linked,
        first_name="Kind",
        last_name="B",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=linked,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert [target["token"] for target in response.context["checkin_participants"]] == [
        f"participant-{participant.pk}",
        f"participant-{linked.pk}",
        f"family-{linked_companion.pk}",
        f"family-{linked_child.pk}",
    ]


@pytest.mark.django_db
def test_kiosk_checkin_updates_linked_participant_dates(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    linked = ParticipantFactory(camp=camp, first_name="Grace", last_name="B")
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=linked,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    linked_token = f"participant-{linked.pk}"
    checkin_state_tokens = _checkin_state_tokens(kiosk_client)

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [linked_token],
            f"arrival_date_{linked_token}": "2026-07-03",
            f"departure_date_{linked_token}": "2026-07-09",
            f"checkin_state_{linked_token}": checkin_state_tokens[linked_token],
        },
    )

    assert response.status_code == 302
    linked.refresh_from_db()
    assert linked.arrival_date == date(2026, 7, 3)
    assert linked.departure_date == date(2026, 7, 9)
    assert linked.booked_nights == 6


@pytest.mark.django_db
def test_kiosk_checkin_rejects_unlinked_participant(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    unlinked = ParticipantFactory(camp=camp, first_name="Grace", last_name="B")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [f"participant-{unlinked.pk}"],
            f"arrival_date_participant-{unlinked.pk}": "2026-07-02",
            f"departure_date_participant-{unlinked.pk}": "2026-07-10",
        },
    )

    assert response.status_code == 200
    unlinked.refresh_from_db()
    assert unlinked.arrival_date is None
    assert unlinked.departure_date is None
    assert "Ein Teilnehmer darf über diesen Kiosk nicht bearbeitet werden.".encode() in response.content


@pytest.mark.django_db
def test_kiosk_checkin_rejects_departure_before_arrival(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    participant_token = f"participant-{participant.pk}"
    checkin_state_tokens = _checkin_state_tokens(kiosk_client)

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [participant_token],
            f"arrival_date_{participant_token}": "2026-07-10",
            f"departure_date_{participant_token}": "2026-07-02",
            f"checkin_state_{participant_token}": checkin_state_tokens[participant_token],
        },
    )

    assert response.status_code == 200
    participant.refresh_from_db()
    assert participant.arrival_date is None
    assert participant.departure_date is None
    assert "Die Abreise für Ada A muss nach der Anreise liegen.".encode() in response.content


@pytest.mark.django_db
def test_kiosk_checkin_rejects_tampered_original_state(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    participant = ParticipantFactory(camp=camp)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    participant_token = f"participant-{participant.pk}"
    checkin_state_tokens = _checkin_state_tokens(kiosk_client)

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [participant_token],
            f"arrival_date_{participant_token}": "2026-07-02",
            f"departure_date_{participant_token}": "2026-07-10",
            f"checkin_state_{participant_token}": (checkin_state_tokens[participant_token] + "tampered"),
        },
    )

    participant.refresh_from_db()
    assert response.status_code == 200
    assert participant.arrival_date is None
    assert participant.departure_date is None
    assert "Die Check-in-Daten konnten nicht bestätigt werden." in response.content.decode("utf-8")


@pytest.mark.django_db
def test_kiosk_checkin_updates_companion_and_child_targets(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="A",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    child = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Kind",
        last_name="A",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    companion_token = f"family-{companion.pk}"
    child_token = f"family-{child.pk}"
    checkin_state_tokens = _checkin_state_tokens(kiosk_client)

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [companion_token, child_token],
            f"arrival_date_{companion_token}": "2026-07-02",
            f"departure_date_{companion_token}": "2026-07-10",
            f"checkin_state_{companion_token}": checkin_state_tokens[companion_token],
            f"arrival_date_{child_token}": "2026-07-03",
            f"departure_date_{child_token}": "2026-07-09",
            f"checkin_state_{child_token}": checkin_state_tokens[child_token],
        },
    )

    assert response.status_code == 302
    companion.refresh_from_db()
    child.refresh_from_db()
    assert companion.arrival_date == date(2026, 7, 2)
    assert companion.departure_date == date(2026, 7, 10)
    assert child.arrival_date == date(2026, 7, 3)
    assert child.departure_date == date(2026, 7, 9)


@pytest.mark.django_db
def test_kiosk_home_checkin_dialog_lists_companion_and_child(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="A")
    ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="A",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Kind",
        last_name="A",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode()
    checkin_dialog = content[content.index('id="checkin-dialog"') :]
    assert "Grace A" in checkin_dialog
    assert "Kind A" in checkin_dialog


@pytest.mark.django_db
def test_kiosk_home_shows_leadership_contact_button(kiosk_client):
    camp = CampFactory()
    admin_user = UserFactory(username="leitung", email="leitung@example.test")
    admin_user.is_superuser = True
    admin_user.save()
    UserProfile.objects.create(user=admin_user, phone="0123 / 456")
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"Kontakt Lagerleitung" in response.content
    assert response.content.count(b"Kontakt Lagerleitung") == 2
    assert b"leitung@example.test" in response.content
    assert b'href="tel:0123456"' in response.content
    assert b"0123 / 456" in response.content


@pytest.mark.django_db
def test_kiosk_home_renders_balance_with_correct_signs(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    Payment.objects.create(participant=participant, amount=Decimal("15.00"), paid_on=date(2026, 7, 1))
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"+15,00 \xe2\x82\xac" in response.content


@pytest.mark.django_db
def test_kiosk_shared_expense_upload_shows_receipt_link_and_serves_file(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    receipt_content = b"%PDF-1.7\ntest receipt"
    receipt = SimpleUploadedFile("rechnung.pdf", receipt_content, content_type="application/pdf")
    response = kiosk_client.post(
        reverse("kiosk-shared-expense-request"),
        {
            "category": "Verbrauchsmaterial",
            "description": "Schrauben",
            "amount": "12.50",
            "paid_on": "2026-07-01",
            "receipt": receipt,
        },
    )

    assert response.status_code == 302
    expense = Expense.objects.get(participant=participant, description="Schrauben")
    try:
        assert expense.receipt.name.startswith("receipts/rechnung")
        assert expense.receipt.url.startswith("/media/receipts/")

        receipt_url = reverse("expense-receipt", args=[expense.pk])
        home_response = kiosk_client.get(reverse("kiosk-home"))
        assert home_response.status_code == 200
        assert b"Beleg" in home_response.content
        assert receipt_url.encode() in home_response.content

        assert Path(expense.receipt.path).exists()
        file_response = kiosk_client.get(receipt_url)
        assert file_response.status_code == 200
        assert b"".join(file_response.streaming_content) == receipt_content
    finally:
        expense.receipt.delete(save=False)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "home_route_name"),
    [
        ("kiosk-shared-expense-request", "kiosk-home"),
        ("central-kiosk-shared-expense-request", "central-kiosk-home"),
    ],
)
def test_pre_camp_kiosk_shared_expense_posts_cannot_create_expenses(kiosk_client, route_name, home_route_name):
    camp = CampFactory(
        year=2099,
        starts_on=date(2099, 7, 31),
        ends_on=date(2099, 8, 14),
    )
    participant = ParticipantFactory(camp=camp)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse(route_name),
        {
            "category": "Verbrauchsmaterial",
            "description": "Schrauben",
            "amount": "12.50",
            "paid_on": "2099-08-01",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse(home_route_name)
    assert not Expense.objects.filter(participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_shared_expense_upload_rejects_unsupported_receipt_type(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    receipt = SimpleUploadedFile("rechnung.txt", b"not a receipt", content_type="text/plain")
    response = kiosk_client.post(
        reverse("kiosk-shared-expense-request"),
        {
            "category": "Verbrauchsmaterial",
            "description": "Schrauben",
            "amount": "12.50",
            "paid_on": "2026-07-01",
            "receipt": receipt,
        },
    )

    assert response.status_code == 200
    assert not Expense.objects.filter(participant=participant, description="Schrauben").exists()
    assert b"Erlaubte Dateitypen" in response.content


@pytest.mark.django_db
def test_kiosk_shared_expense_upload_rejects_oversized_receipt(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    receipt = SimpleUploadedFile("rechnung.pdf", b"x" * (5 * 1024 * 1024 + 1), content_type="application/pdf")
    response = kiosk_client.post(
        reverse("kiosk-shared-expense-request"),
        {
            "category": "Verbrauchsmaterial",
            "description": "Schrauben",
            "amount": "12.50",
            "paid_on": "2026-07-01",
            "receipt": receipt,
        },
    )

    assert response.status_code == 200
    assert not Expense.objects.filter(participant=participant, description="Schrauben").exists()
    assert "höchstens 5 MB".encode() in response.content


@pytest.mark.django_db
def test_kiosk_expense_receipt_rejects_other_participants(kiosk_client):
    camp = CampFactory()
    viewer = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    owner = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    expense = ExpenseFactory(
        participant=owner,
        camp=camp,
        description="Fremder Beleg",
        receipt=SimpleUploadedFile("fremd.pdf", b"private receipt", content_type="application/pdf"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = viewer.pk
    session.save()

    try:
        response = kiosk_client.get(reverse("expense-receipt", args=[expense.pk]))

        assert response.status_code == 403
    finally:
        expense.receipt.delete(save=False)


@pytest.mark.django_db
def test_kiosk_home_sorts_shared_expense_cards_by_status_and_recency(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    approved = ExpenseFactory(
        participant=participant,
        camp=camp,
        description="Genehmigter Einkauf",
        status=Expense.Status.APPROVED,
    )
    rejected = ExpenseFactory(
        participant=participant,
        camp=camp,
        description="Abgelehnter Einkauf",
        status=Expense.Status.REJECTED,
    )
    pending_older = ExpenseFactory(
        participant=participant,
        camp=camp,
        description="Alter offener Einkauf",
        status=Expense.Status.PENDING,
    )
    pending_newer = ExpenseFactory(
        participant=participant,
        camp=camp,
        description="Neuer offener Einkauf",
        status=Expense.Status.PENDING,
    )
    Expense.objects.filter(pk=pending_older.pk).update(created_at=timezone.now() - timedelta(days=2))
    Expense.objects.filter(pk=pending_newer.pk).update(created_at=timezone.now() - timedelta(days=1))
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert [expense.pk for expense in response.context["participant_expenses"]] == [
        pending_newer.pk,
        pending_older.pk,
        rejected.pk,
        approved.pk,
    ]


@pytest.mark.django_db
def test_kiosk_home_renders_shared_expense_cards_with_receipt_and_rejection_details(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    rejected = ExpenseFactory(
        participant=participant,
        camp=camp,
        description="Grillgut für alle mit einer langen Beschreibung",
        amount=Decimal("42.00"),
        paid_on=date(2026, 7, 2),
        status=Expense.Status.REJECTED,
        rejection_reason="Der Beleg ist nicht lesbar.",
    )
    pending = ExpenseFactory(
        participant=participant,
        camp=camp,
        description="Getränkekisten",
        amount=Decimal("18.50"),
        paid_on=date(2026, 7, 3),
        status=Expense.Status.PENDING,
        receipt=SimpleUploadedFile("kisten.pdf", b"receipt", content_type="application/pdf"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    try:
        response = kiosk_client.get(reverse("kiosk-home"))

        assert response.status_code == 200
        content = response.content
        assert content.count(b'class="shared-expense-card"') == 2
        assert f'data-expense-id="{rejected.pk}"'.encode() in content
        assert "Grillgut für alle mit einer langen Beschreibung".encode() in content
        assert "42,00 €".encode() in content
        assert b'datetime="2026-07-02"' in content
        assert b"Kein Beleg" in content
        assert b"kiosk-status-text kiosk-status-text--danger" in content
        assert b"<summary>Ablehnungsgrund anzeigen</summary>" in content
        assert b"Der Beleg ist nicht lesbar." in content
        assert b"rejection-reason-dialog" not in content
        assert reverse("expense-receipt", args=[pending.pk]).encode() in content
    finally:
        pending.receipt.delete(save=False)


@pytest.mark.django_db
def test_kiosk_home_renders_only_ordered_core_cards_and_menu_dialogs(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    inviter = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    ParticipantBookingLink.objects.create(inviter=inviter, invitee=participant)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content
    assert b"data-kiosk-masonry" in content
    card_markers = [
        b'data-kiosk-card="drinks"',
        b'data-kiosk-card="food"',
        b'data-kiosk-card="shifts"',
        b'data-kiosk-card="check-in"',
    ]
    positions = [content.index(marker) for marker in card_markers]
    assert positions == sorted(positions)
    visible_section_positions = [
        content.index(b'class="kiosk-hero"'),
        content.index(b"Aktuelle Abrechnung"),
        content.index(b"<h2>Einladungen</h2>"),
        *positions,
    ]
    assert visible_section_positions == sorted(visible_section_positions)
    assert content.count(b"data-kiosk-card=") == 4
    food_card_end = content.index(b"</section>", positions[1])
    food_card = content[positions[1] : food_card_end]
    assert b'data-dialog-target="meal-calendar-dialog"' in food_card
    assert b'data-dialog-target="breakfast-meal-calendar"' not in food_card
    assert "Buche hier Frühstück, Snacks und Abendessen.".encode() in food_card
    for dialog_id in (
        b"kiosk-menu-dialog",
        b"meal-calendar-dialog",
        b"quick-bookings-dialog",
        b"shared-expenses-dialog",
        b"family-management-dialog",
    ):
        assert b'id="' + dialog_id + b'"' in content
    assert b'id="booking-links-dialog"' not in content
    assert "Noch keine Anträge eingereicht.".encode() in content


@pytest.mark.django_db
def test_kiosk_home_shows_order_sent_for_next_day(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 10, 30))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 3),
        meal_booking_cutoff_time=time(12, 0),
    )
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    MealOrder.objects.create(camp=camp, meal_date=date(2026, 7, 2))
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"Die Bestellung wurde abgeschickt." in response.content
    content = response.content.decode()
    next_day_start = content.index('data-open-meal-day-detail="meal-day-detail-2026-07-02"')
    next_day_end = content.index("</button>", next_day_start)
    assert "Geschlossen" in content[next_day_start:next_day_end]
    assert 'data-meal-date="2026-07-02"' not in content


@pytest.mark.django_db
def test_kiosk_rejects_meal_booking_after_order_was_sent(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 10, 30))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 2),
        meal_booking_cutoff_time=time(14, 45),
    )
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    meal_date = date(2026, 7, 2)
    MealOrder.objects.create(camp=camp, meal_date=meal_date)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": [meal_date.isoformat()],
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
            "meal-target": [f"participant-{participant.pk}"],
            f"meal-variant-participant-{participant.pk}": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert "Die Bestellung für 02.07.2026 wurde bereits abgeschickt.".encode() in response.content
    assert not MealSignup.objects.filter(participant=participant, meal_date=meal_date).exists()


@pytest.mark.django_db
def test_kiosk_menu_explains_destinations_and_has_an_explicit_trigger(kiosk_client):
    participant = ParticipantFactory()
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'aria-controls="kiosk-menu-dialog"' in content
    assert 'aria-haspopup="dialog"' in content
    assert "Weitere Bereiche öffnen" in content
    assert "Abendessen (Kalender)" in content
    assert "Abendessen nach Lagertag buchen und verwalten." in content
    assert "Letzte Schnellbuchungen" in content
    assert "Getränke, Frühstück und Snacks prüfen oder stornieren." in content


@pytest.mark.django_db
def test_kiosk_home_shows_meal_booking_cutoff_time_before_order_sent(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 10, 30))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(meal_booking_cutoff_time=time(14, 45))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"Die Buchung ist bis 14:45 Uhr m\xc3\xb6glich." in response.content


@pytest.mark.django_db
def test_kiosk_meal_calendar_renders_all_camp_days_with_menu_and_participant_price(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 6, 30, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=date(2026, 7, 3))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    MealPlanEntry.objects.create(
        camp=camp,
        meal_date=date(2026, 7, 2),
        meal=MealSignup.Meal.DINNER,
        description="Pasta mit Salat",
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode()
    calendar_start = content.index('<div class="meal-status-calendar"')
    calendar_end = content.index("</div>", calendar_start)
    status_calendar = content[calendar_start:calendar_end]
    assert 'data-meal-date="2026-07-01"' in content
    assert 'data-meal-date="2026-07-02"' in content
    assert 'data-meal-date="2026-07-03"' in content
    assert "Pasta mit Salat" in status_calendar
    assert "7,00 €" in status_calendar
    assert "Menü" in content
    assert "7,00 €" in content


@pytest.mark.django_db
def test_kiosk_meal_calendar_shows_closed_days_without_booking_action(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 2, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 3))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Geschlossen" in content
    assert "Nicht auswählbar" in content
    assert "Buchungen und Rücknahmen für 01.07.2026 sind geschlossen." in content
    assert 'data-meal-date="2026-07-01"' not in content
    assert 'data-meal-date="2026-07-03"' in content


@pytest.mark.django_db
def test_kiosk_home_shows_contact_hint_after_cutoff_before_order_sent(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 18, 30))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(meal_booking_cutoff_time=time(12, 0))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode()
    meal_section_start = content.index('id="meal-calendar-dialog"')
    assert "melde dich bitte bei der Lagerleitung" in content[meal_section_start:]
    status_start = content.index("Die Buchung ist geschlossen.")
    calendar_start = content.index('<div class="meal-status-calendar"')
    assert meal_section_start < status_start < calendar_start


@pytest.mark.django_db
def test_kiosk_meal_status_calendar_shows_day_states_and_detail_dialog(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 7, 1, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 3))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    active_signup = MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 2),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )
    MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 3),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.VEGAN,
        status=MealSignup.Status.RETRACTED,
        retracted_at=timezone.now(),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    content = response.content.decode()
    assert response.status_code == 200
    assert content.count("meal-status-day") >= 3
    assert "meal-status-day meal-status-day--closed" in content
    assert "meal-status-day meal-status-day--booked" in content
    assert "meal-status-day meal-status-day--retracted" in content
    assert 'id="meal-day-detail-2026-07-02"' in content
    assert f'name="meal_signup_id" value="{active_signup.pk}"' in content
    assert "Gebucht für" in content
    assert "Ada Lovelace" in content
    assert "Essensanmeldungen</h2>" not in content
    assert "meal-signup-compact" not in content


@pytest.mark.django_db
def test_kiosk_meal_day_detail_opens_booking_for_the_selected_date(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 7, 1, 10, 0)))
    meal_date = date(2026, 7, 2)
    camp = CampFactory(
        starts_on=meal_date,
        ends_on=meal_date,
        allow_dinner_prebooking_before_camp=True,
    )
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    MealPlanEntry.objects.create(
        camp=camp,
        meal_date=meal_date,
        meal=MealSignup.Meal.DINNER,
        description="Kartoffelsuppe mit Brot",
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    content = response.content.decode()
    detail_start = content.index('id="meal-day-detail-2026-07-02"')
    detail_end = content.index("</dialog>", detail_start)
    day_detail = content[detail_start:detail_end]
    assert response.status_code == 200
    assert "Essen für diesen Tag buchen" in day_detail
    assert "data-open-meal-dialog" in day_detail
    assert 'data-meal-date="2026-07-02"' in day_detail
    assert 'data-meal="dinner"' in day_detail
    assert 'data-meal-label="Abendessen"' in day_detail
    assert "Kartoffelsuppe mit Brot" in day_detail
    assert "Preis: 7,00 €" in day_detail
    assert 'id="meal-dialog-close"' in content
    assert "über “Essen buchen”" not in day_detail


@pytest.mark.django_db
def test_kiosk_meal_day_detail_uses_price_rule_name_and_shows_free_price(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 7, 1, 10, 0)))
    meal_date = date(2026, 7, 2)
    camp = CampFactory(
        starts_on=meal_date,
        ends_on=meal_date,
        allow_dinner_prebooking_before_camp=True,
    )
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        name="Kostenloses Abendessen",
        unit_price=Decimal("0.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    content = response.content.decode()
    detail_start = content.index('id="meal-day-detail-2026-07-02"')
    detail_end = content.index("</dialog>", detail_start)
    day_detail = content[detail_start:detail_end]
    assert response.status_code == 200
    assert "Kostenloses Abendessen" in day_detail
    assert "Preis: 0,00 €" in day_detail


@pytest.mark.django_db
def test_kiosk_meal_booking_dialog_shows_all_camp_days_with_prices(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 7, 1, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 3))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Nudeln mit Salat",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    content = response.content.decode()
    assert response.status_code == 200
    assert 'class="meal-booking-calendar"' in content
    assert content.count("meal-booking-day") >= 3
    assert "Nudeln mit Salat" in content
    assert "7,00 €" in content
    assert 'data-meal-date-select="2026-07-02"' in content
    assert 'data-meal-date-select="2026-07-01"' in content
    assert 'data-meal-date-select="2026-07-01"' in content and "disabled" in content


@pytest.mark.django_db
def test_kiosk_meal_booking_dialog_keeps_child_only_price_day_selectable(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 7, 1, 10, 0)))
    camp = CampFactory(
        starts_on=date(2026, 7, 2),
        ends_on=date(2026, 7, 2),
        allow_dinner_prebooking_before_camp=True,
    )
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace", is_child=False)
    ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Kind",
        last_name="Lovelace",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=True,
        applies_to_adults=False,
        name="Kinder-Abendessen",
        unit_price=Decimal("4.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    content = response.content.decode()
    assert response.status_code == 200
    assert 'data-meal-date="2026-07-02"' in content
    assert "Kinder-Abendessen" in content
    assert "4,00 €" in content


@pytest.mark.django_db
def test_kiosk_books_drink_with_camp_drink_price_and_subsidy_flag(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(
        camp=camp,
        first_name="Ada",
        last_name="Lovelace",
        is_youth_group=True,
        hilfssatz=Decimal("0.5000"),
        berufssatz=Decimal("0.3300"),
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        name="Getränk",
        unit_price=Decimal("2.50"),
        foerdersatz=Decimal("1.0000"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "quick",
            "quick-price_rule": PriceRule.objects.get(camp=camp, kind=PriceRule.Kind.DRINK).pk,
            "quick-quantity": 2,
        },
    )

    assert response.status_code == 302
    entry = Charge.objects.get(participant=participant, kind=Charge.Kind.DRINK)
    assert entry.description == "Getränk (Kiosk)"
    assert entry.quantity == Decimal("2.00")
    assert entry.unit_price == Decimal("2.50")
    assert entry.foerdersatz == Decimal("1.0000")
    assert entry.kiosk_booked_by == participant


@pytest.mark.django_db
def test_kiosk_quick_booking_rejects_explicitly_empty_target_selection(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    rule = PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        name="Wasser",
        unit_price=Decimal("1.50"),
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
            "quick-targets-submitted": "1",
        },
    )

    assert response.status_code == 200
    assert "Bitte mindestens eine Person auswählen." in response.content.decode("utf-8")
    assert not Charge.objects.exists()


@pytest.mark.django_db
def test_kiosk_can_cancel_own_quick_booking_within_cancel_window(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.DRINK,
        description="Wasser (Kiosk)",
        quantity=Decimal("1.00"),
        unit_price=Decimal("1.50"),
        kiosk_booked_by=participant,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 302
    charge.refresh_from_db()
    assert charge.deleted_at is not None
    assert charge.deleted_by is None


@pytest.mark.django_db
def test_kiosk_rejects_quick_booking_cancel_after_cancel_window(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.DRINK,
        description="Wasser (Kiosk)",
        quantity=Decimal("1.00"),
        unit_price=Decimal("1.50"),
        kiosk_booked_by=participant,
    )
    Charge.objects.filter(pk=charge.pk).update(created_at=timezone.now() - timedelta(minutes=16))
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 200
    charge.refresh_from_db()
    assert charge.deleted_at is None


@pytest.mark.django_db
def test_kiosk_allows_quick_booking_cancel_after_charge_appeared_in_settlement_snapshot(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.DRINK,
        description="Wasser (Kiosk)",
        quantity=Decimal("1.00"),
        unit_price=Decimal("1.50"),
        occurred_on=timezone.localdate(),
        kiosk_booked_by=participant,
    )
    run = create_settlement_run(camp, UserFactory())
    snapshot = run.settlements.get(participant=participant)
    snapshot_data = snapshot.data
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 302
    charge.refresh_from_db()
    assert charge.deleted_at is not None
    snapshot.refresh_from_db()
    assert snapshot.data == snapshot_data


@pytest.mark.django_db
def test_kiosk_allows_quick_booking_cancel_when_charge_is_not_in_earlier_settlement_snapshot(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    create_settlement_run(camp, UserFactory())
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Frühstück (Kiosk)",
        quantity=Decimal("1.00"),
        unit_price=Decimal("4.00"),
        occurred_on=timezone.localdate() + timedelta(days=1),
        kiosk_booked_by=participant,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 302
    charge.refresh_from_db()
    assert charge.deleted_at is not None


@pytest.mark.django_db
def test_kiosk_rejects_quick_booking_cancel_for_unrelated_participant(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    other = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    charge = Charge.objects.create(
        participant=other,
        kind=Charge.Kind.DRINK,
        description="Wasser (Kiosk)",
        quantity=Decimal("1.00"),
        unit_price=Decimal("1.50"),
        kiosk_booked_by=other,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 200
    charge.refresh_from_db()
    assert charge.deleted_at is None


@pytest.mark.django_db
def test_kiosk_linked_quick_booking_can_be_cancelled_by_booking_participant(kiosk_client):
    camp = CampFactory()
    booker = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    linked = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    ParticipantBookingLink.objects.create(
        inviter=booker,
        invitee=linked,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    PriceRuleFactory(camp=camp, kind=PriceRule.Kind.DRINK, name="Wasser", unit_price=Decimal("1.50"))
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = booker.pk
    session.save()
    kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "quick",
            "quick-price_rule": PriceRule.objects.get(camp=camp, kind=PriceRule.Kind.DRINK).pk,
            "quick-quantity": 1,
            "quick-target": [f"participant-{linked.pk}"],
        },
    )
    charge = Charge.objects.get(participant=linked, kind=Charge.Kind.DRINK)

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 302
    charge.refresh_from_db()
    assert charge.kiosk_booked_by == booker
    assert charge.deleted_at is not None


@pytest.mark.django_db
def test_kiosk_billed_linked_participant_can_cancel_own_quick_booking(kiosk_client):
    camp = CampFactory()
    booker = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    linked = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    charge = Charge.objects.create(
        participant=linked,
        kind=Charge.Kind.DRINK,
        description="Wasser (Kiosk) für Grace Hopper",
        quantity=Decimal("1.00"),
        unit_price=Decimal("1.50"),
        kiosk_booked_by=booker,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = linked.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 302
    charge.refresh_from_db()
    assert charge.deleted_at is not None


@pytest.mark.django_db
def test_kiosk_home_shows_quick_booking_cancel_action(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Frühstück (Kiosk)",
        quantity=Decimal("1.00"),
        unit_price=Decimal("4.00"),
        kiosk_booked_by=participant,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Letzte Schnellbuchungen" in content
    assert "quick_cancel" in content
    assert "Stornieren" in content
    assert 'class="quick-booking-list"' in content
    assert "data-open-quick-cancel-dialog" in content
    assert 'id="quick-cancel-dialog"' in content


@pytest.mark.django_db
def test_kiosk_home_filters_quick_booking_list_to_kiosk_created_charges(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    quick_charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.DRINK,
        description="Wasser (Kiosk)",
        quantity=Decimal("1.00"),
        unit_price=Decimal("1.50"),
        kiosk_booked_by=participant,
    )
    for index in range(9):
        Charge.objects.create(
            participant=participant,
            kind=Charge.Kind.FOOD,
            description=f"Admin-Essen {index}",
            quantity=Decimal("1.00"),
            unit_price=Decimal("7.00"),
        )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert f'data-charge-id="{quick_charge.pk}"' in content
    assert content.count('name="action" value="quick_cancel"') == 1


@pytest.mark.django_db
def test_kiosk_meal_signup_ignores_client_price_tampering_and_uses_server_rule(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=date(2026, 7, 2))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
        foerdersatz=Decimal("0"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    payload = {
        "action": "meal",
        "meal-meal_dates": date(2026, 7, 1).isoformat(),
        "meal-meal": MealSignup.Meal.DINNER,
        "meal-variant": MealSignup.Variant.NORMAL,
        "meal-unit_price": "0.01",
        "meal-foerdersatz": "100",
    }
    kiosk_client.post(reverse("kiosk-home"), payload)
    payload["meal-variant"] = MealSignup.Variant.VEGAN
    response = kiosk_client.post(reverse("kiosk-home"), payload)

    assert response.status_code == 302
    signup = MealSignup.objects.get(participant=participant)
    assert signup.variant == MealSignup.Variant.VEGAN
    charge = Charge.objects.get(participant=participant, kind=Charge.Kind.FOOD)
    assert charge.description == "Abendessen Abendessen"
    assert charge.unit_price == Decimal("7.00")
    assert signup.charge == charge


@pytest.mark.django_db
def test_kiosk_meal_signup_uses_date_specific_price_only_for_matching_date(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=date(2026, 7, 2))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Standard Abendessen",
        unit_price=Decimal("7.00"),
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        meal_date=date(2026, 7, 2),
        applies_to_children=False,
        applies_to_adults=True,
        name="Grillabend",
        unit_price=Decimal("9.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 302
    normal_charge = Charge.objects.get(participant=participant, occurred_on=date(2026, 7, 1))
    assert normal_charge.description == "Standard Abendessen Abendessen"
    assert normal_charge.unit_price == Decimal("7.00")

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 2).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 302
    special_charge = Charge.objects.get(participant=participant, occurred_on=date(2026, 7, 2))
    assert special_charge.description == "Grillabend Abendessen"
    assert special_charge.unit_price == Decimal("9.00")


@pytest.mark.django_db
def test_kiosk_books_multiple_meal_dates_and_targets_atomically(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    first_date = date(2026, 7, 1)
    second_date = date(2026, 7, 2)
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=second_date)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    selected = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    unselected = ParticipantFactory(camp=camp, first_name="Katherine", last_name="Johnson")
    for linked in (selected, unselected):
        ParticipantBookingLink.objects.create(
            inviter=participant,
            invitee=linked,
            status=ParticipantBookingLink.Status.ACCEPTED,
        )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Standard Abendessen",
        unit_price=Decimal("7.00"),
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        meal_date=second_date,
        applies_to_children=False,
        applies_to_adults=True,
        name="Grillabend",
        unit_price=Decimal("9.00"),
    )
    existing_charge = Charge.objects.create(
        participant=selected,
        kind=Charge.Kind.FOOD,
        description="Alte Buchung",
        quantity=1,
        unit_price=Decimal("6.00"),
        occurred_on=first_date,
    )
    existing_signup = MealSignup.objects.create(
        participant=selected,
        meal_date=first_date,
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        charge=existing_charge,
    )
    untouched_signup = MealSignup.objects.create(
        participant=unselected,
        meal_date=second_date,
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": [first_date.isoformat(), second_date.isoformat()],
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
            "meal-target": [f"participant-{participant.pk}", f"participant-{selected.pk}"],
            f"meal-variant-participant-{participant.pk}": MealSignup.Variant.VEGAN,
            f"meal-variant-participant-{selected.pk}": MealSignup.Variant.VEGAN,
        },
    )

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('kiosk-home')}?dialog=meal-calendar"
    assert (
        MealSignup.objects.filter(
            participant__in=[participant, selected],
            meal_date__in=[first_date, second_date],
            status=MealSignup.Status.ACTIVE,
        ).count()
        == 4
    )
    existing_signup.refresh_from_db()
    existing_charge.refresh_from_db()
    untouched_signup.refresh_from_db()
    assert existing_signup.variant == MealSignup.Variant.VEGAN
    assert existing_charge.description == "Standard Abendessen Abendessen"
    assert existing_charge.unit_price == Decimal("7.00")
    assert untouched_signup.variant == MealSignup.Variant.NORMAL
    assert Charge.objects.get(participant=participant, occurred_on=second_date).unit_price == Decimal("9.00")
    assert Charge.objects.get(participant=selected, occurred_on=second_date).unit_price == Decimal("9.00")


@pytest.mark.django_db
def test_kiosk_rejects_entire_meal_batch_when_one_date_has_no_price(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    first_date = date(2026, 7, 1)
    second_date = date(2026, 7, 2)
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=second_date)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        meal_date=first_date,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen erster Tag",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": [first_date.isoformat(), second_date.isoformat()],
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert b"02.07.2026" in response.content
    assert response.context["meal_dialog_open"] is True
    assert {day["date"] for day in response.context["meal_calendar_days"] if day["selected"]} == {
        first_date,
        second_date,
    }
    assert not MealSignup.objects.filter(participant=participant).exists()
    assert not Charge.objects.filter(participant=participant, kind=Charge.Kind.FOOD).exists()


@pytest.mark.django_db
def test_kiosk_rejects_entire_meal_batch_when_one_date_is_locked(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 10, 0))
    _freeze_meal_lock_time(monkeypatch, fixed_now)
    first_date = fixed_now.date()
    second_date = first_date + timedelta(days=1)
    camp = CampFactory(starts_on=first_date, ends_on=second_date)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": [first_date.isoformat(), second_date.isoformat()],
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert "Buchungen und Rücknahmen".encode() in response.content
    assert not MealSignup.objects.filter(participant=participant).exists()
    assert not Charge.objects.filter(participant=participant, kind=Charge.Kind.FOOD).exists()


@pytest.mark.django_db
def test_kiosk_normalizes_duplicate_meal_dates(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    meal_date = date(2026, 7, 1)
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=meal_date)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": [meal_date.isoformat(), meal_date.isoformat()],
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 302
    assert MealSignup.objects.filter(participant=participant, meal_date=meal_date).count() == 1
    assert Charge.objects.filter(participant=participant, occurred_on=meal_date, kind=Charge.Kind.FOOD).count() == 1


@pytest.mark.django_db
def test_kiosk_rejects_meal_date_outside_configured_camp(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=date(2026, 7, 2))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 3).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert "meal_dates" in response.context["meal_form"].errors
    assert not MealSignup.objects.filter(participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_rejects_unknown_meal_target_without_partial_booking(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    meal_date = date(2026, 7, 1)
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=meal_date)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": meal_date.isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
            "meal-target": [f"participant-{participant.pk}", "participant-999999"],
        },
    )

    assert response.status_code == 200
    assert "nicht verfügbar".encode() in response.content
    participant_target = next(
        target for target in response.context["meal_targets"] if target["token"] == f"participant-{participant.pk}"
    )
    assert participant_target["meal_selected"] is True
    assert not MealSignup.objects.filter(participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_meal_signup_for_tomorrow_closes_after_camp_cutoff(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 12, 1))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 2),
        meal_booking_cutoff_time=time(12, 0),
    )
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 2).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert b"sind nach 12:00 Uhr geschlossen" in response.content
    assert not MealSignup.objects.filter(participant=participant).exists()
    assert not Charge.objects.filter(participant=participant, kind=Charge.Kind.FOOD).exists()


@pytest.mark.django_db
def test_kiosk_meal_signup_for_tomorrow_stays_open_before_camp_cutoff(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 11, 59))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 2),
        meal_booking_cutoff_time=time(12, 0),
    )
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 2).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 302
    assert MealSignup.objects.filter(participant=participant, status=MealSignup.Status.ACTIVE).exists()


@pytest.mark.django_db
def test_kiosk_meal_signup_for_past_date_is_locked(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 2, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert b"Buchungen und R\xc3\xbccknahmen" in response.content
    assert not MealSignup.objects.filter(participant=participant).exists()
    assert not Charge.objects.filter(participant=participant, kind=Charge.Kind.FOOD).exists()


@pytest.mark.django_db
def test_kiosk_meal_signup_for_today_is_locked(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 2, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 2).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert b"Buchungen und R\xc3\xbccknahmen" in response.content
    assert not MealSignup.objects.filter(participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_retracts_meal_signup_and_soft_deletes_food_charge(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 7, 1, 10, 0)))
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen Abendessen",
        quantity=1,
        unit_price=Decimal("7.00"),
        occurred_on=date(2026, 7, 2),
    )
    signup = MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 2),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        charge=charge,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "meal_retract", "meal_signup_id": signup.pk})

    assert response.status_code == 302
    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.status == MealSignup.Status.RETRACTED
    assert signup.retracted_at is not None
    assert charge.deleted_at is not None


@pytest.mark.django_db
def test_kiosk_allows_meal_retraction_after_charge_appeared_in_settlement_snapshot(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 7, 1, 10, 0)))
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=1,
        unit_price=Decimal("7.00"),
        occurred_on=date(2026, 7, 2),
    )
    signup = MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 2),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        charge=charge,
    )
    run = create_settlement_run(camp, UserFactory())
    snapshot = run.settlements.get(participant=participant)
    snapshot_data = snapshot.data
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "meal_retract", "meal_signup_id": signup.pk})

    assert response.status_code == 302
    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.status == MealSignup.Status.RETRACTED
    assert signup.retracted_at is not None
    assert charge.deleted_at is not None
    snapshot.refresh_from_db()
    assert snapshot.data == snapshot_data


@pytest.mark.django_db
def test_kiosk_still_rejects_snapshotted_meal_retraction_after_catering_order(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 7, 1, 10, 0)))
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=1,
        unit_price=Decimal("7.00"),
        occurred_on=date(2026, 7, 2),
    )
    signup = MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 2),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        charge=charge,
    )
    create_settlement_run(camp, UserFactory())
    MealOrder.objects.create(camp=camp, meal_date=signup.meal_date)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "meal_retract", "meal_signup_id": signup.pk})

    assert response.status_code == 200
    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.status == MealSignup.Status.ACTIVE
    assert signup.retracted_at is None
    assert charge.deleted_at is None


@pytest.mark.django_db
def test_kiosk_rejects_retraction_for_past_meal_signup(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 2, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen Abendessen",
        quantity=1,
        unit_price=Decimal("7.00"),
        occurred_on=date(2026, 7, 1),
    )
    signup = MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        charge=charge,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "meal_retract", "meal_signup_id": signup.pk})

    assert response.status_code == 200
    assert b"Buchungen und R\xc3\xbccknahmen" in response.content
    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.status == MealSignup.Status.ACTIVE
    assert signup.retracted_at is None
    assert charge.deleted_at is None


@pytest.mark.django_db
def test_kiosk_rejects_retraction_for_today_meal_signup(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 2, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen Abendessen",
        quantity=1,
        unit_price=Decimal("7.00"),
        occurred_on=date(2026, 7, 2),
    )
    signup = MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 2),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        charge=charge,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-home"), {"action": "meal_retract", "meal_signup_id": signup.pk})

    assert response.status_code == 200
    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.status == MealSignup.Status.ACTIVE
    assert signup.retracted_at is None
    assert charge.deleted_at is None


@pytest.mark.django_db
def test_kiosk_meal_signup_requires_person_when_dialog_selection_is_empty(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-targets-submitted": "1",
            "meal-meal_dates": date(2026, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert "Bitte mindestens eine Person auswählen.".encode() in response.content
    assert not MealSignup.objects.filter(participant=participant).exists()
    assert not Charge.objects.filter(participant=participant, kind=Charge.Kind.FOOD).exists()


@pytest.mark.django_db
def test_kiosk_cannot_self_award_family_subsidy_when_creating_member_and_booking_meal(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=date(2026, 7, 2))
    participant = ParticipantFactory(camp=camp, first_name="Vater", last_name="Muster")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=True,
        applies_to_adults=False,
        name="Abendessen Kind",
        unit_price=Decimal("4.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_create",
            "family-first_name": "Kind",
            "family-last_name": "Muster",
            "family-role": ParticipantFamilyMember.Role.CHILD,
            "family-is_youth_group": "on",
            "family-confirm_settlement_change": "on",
        },
    )

    assert response.status_code == 302
    family_member = ParticipantFamilyMember.objects.get(guardian=participant)
    assert family_member.is_youth_group is False

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
            "meal-target": [f"family-{family_member.pk}"],
            f"meal-variant-family-{family_member.pk}": MealSignup.Variant.NORMAL_CHILD,
        },
    )

    assert response.status_code == 302
    signup = MealSignup.objects.get(participant=participant, family_member=family_member)
    assert signup.variant == MealSignup.Variant.NORMAL_CHILD
    charge = Charge.objects.get(participant=participant, kind=Charge.Kind.FOOD)
    assert charge.description == "Abendessen Kind Abendessen für Kind Muster"
    assert charge.unit_price == Decimal("4.00")
    assert charge.family_member == family_member


@pytest.mark.django_db
def test_kiosk_deactivates_own_family_member(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    family_member = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Byron",
        last_name="Lovelace",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_deactivate",
            "family_member_id": family_member.pk,
        },
    )

    assert response.status_code == 302
    family_member.refresh_from_db()
    assert family_member.is_active is False


@pytest.mark.parametrize(
    ("action", "id_field"),
    [
        ("meal_retract", "meal_signup_id"),
        ("family_member_deactivate", "family_member_id"),
        ("booking_link_accept", "booking_link_id"),
        ("booking_link_decline", "booking_link_id"),
        ("booking_link_revoke", "booking_link_id"),
    ],
)
@pytest.mark.django_db
def test_kiosk_rejects_non_numeric_related_object_ids(kiosk_client, action, id_field):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    before_counts = {
        "meal_signups": MealSignup.objects.count(),
        "family_members": ParticipantFamilyMember.objects.count(),
        "booking_links": ParticipantBookingLink.objects.count(),
    }

    route_name = "kiosk-partner-activity" if action.startswith("booking_link_") else "kiosk-home"
    response = kiosk_client.post(
        reverse(route_name),
        {
            "action": action,
            id_field: "not-an-id",
        },
    )

    assert response.status_code == 200
    assert b"wurde nicht gefunden" in response.content
    assert MealSignup.objects.count() == before_counts["meal_signups"]
    assert ParticipantFamilyMember.objects.count() == before_counts["family_members"]
    assert ParticipantBookingLink.objects.count() == before_counts["booking_links"]


@pytest.mark.django_db
def test_kiosk_shifts_rejects_non_numeric_shift_id_without_side_effect(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    shift = Shift.objects.create(
        camp=camp,
        name="Küchendienst",
        date=date(2026, 7, 1),
        required_slots=1,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-shifts"),
        {
            "action": "signup",
            "shift_id": "not-an-id",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("kiosk-shifts")
    assert not ShiftAssignment.objects.filter(shift=shift).exists()


@pytest.mark.django_db
def test_invalid_partner_invite_stays_on_activity_page(kiosk_client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-partner-activity"),
        {
            "action": "booking_link_invite",
            "link-participant": "",
        },
    )

    assert response.status_code == 200
    assert response.context["booking_link_form"].errors
    assert b"Partner &amp; Aktivit\xc3\xa4ten" in response.content


@pytest.mark.django_db
def test_kiosk_booking_link_invite_accept_revoke_flow(kiosk_client):
    camp = CampFactory()
    inviter = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    invitee = ParticipantFactory(camp=camp, first_name="Grace", last_name="B")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = inviter.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-partner-activity"),
        {
            "action": "booking_link_invite",
            "link-participant": invitee.pk,
        },
    )

    assert response.status_code == 302
    link = ParticipantBookingLink.objects.get(inviter=inviter, invitee=invitee)
    assert link.status == ParticipantBookingLink.Status.PENDING

    session[KIOSK_PARTICIPANT_SESSION_KEY] = invitee.pk
    session.save()
    response = kiosk_client.post(
        reverse("kiosk-partner-activity"),
        {
            "action": "booking_link_accept",
            "booking_link_id": link.pk,
        },
    )

    assert response.status_code == 302
    link.refresh_from_db()
    assert link.status == ParticipantBookingLink.Status.ACCEPTED
    response = kiosk_client.get(reverse("kiosk-home"))
    assert f"participant-{inviter.pk}".encode() in response.content

    response = kiosk_client.post(
        reverse("kiosk-partner-activity"),
        {
            "action": "booking_link_revoke",
            "booking_link_id": link.pk,
        },
    )

    assert response.status_code == 302
    link.refresh_from_db()
    assert link.status == ParticipantBookingLink.Status.REVOKED
    assert list(
        KioskActionAuditLog.objects.filter(booking_link=link).values_list("action", flat=True).order_by("created_at")
    ) == [
        KioskActionAuditLog.Action.LINK_INVITED,
        KioskActionAuditLog.Action.LINK_ACCEPTED,
        KioskActionAuditLog.Action.LINK_REVOKED,
    ]


@pytest.mark.django_db
def test_kiosk_books_meal_for_linked_participant_on_linked_account(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=date(2026, 7, 2))
    inviter = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    invitee = ParticipantFactory(camp=camp, first_name="Grace", last_name="B")
    ParticipantBookingLink.objects.create(
        inviter=inviter,
        invitee=invitee,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = inviter.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
            "meal-target": [f"participant-{invitee.pk}"],
            f"meal-variant-participant-{invitee.pk}": MealSignup.Variant.VEGAN,
        },
    )

    assert response.status_code == 302
    signup = MealSignup.objects.get(participant=invitee)
    assert signup.variant == MealSignup.Variant.VEGAN
    assert not Charge.objects.filter(participant=inviter, kind=Charge.Kind.FOOD).exists()
    charge = Charge.objects.get(participant=invitee, kind=Charge.Kind.FOOD)
    assert charge.description == "Abendessen Abendessen"
    assert charge.unit_price == Decimal("7.00")


@pytest.mark.django_db
def test_kiosk_shows_linked_participant_family_member_meal_signups(kiosk_client):
    camp = CampFactory()
    viewer = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    linked = ParticipantFactory(camp=camp, first_name="Grace", last_name="B")
    family_member = ParticipantFamilyMember.objects.create(
        guardian=linked,
        first_name="Kind",
        last_name="B",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    ParticipantBookingLink.objects.create(
        inviter=viewer,
        invitee=linked,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    MealSignup.objects.create(
        participant=linked,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )
    MealSignup.objects.create(
        participant=linked,
        family_member=family_member,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.BREAKFAST,
        variant=MealSignup.Variant.NORMAL_CHILD,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = viewer.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"Grace B" in response.content
    assert b"Kind B" in response.content
    assert any(signup.family_member_id == family_member.pk for signup in response.context["meal_signups"])


@pytest.mark.django_db
def test_kiosk_drink_form_filters_by_participant_type(kiosk_client):
    camp = CampFactory()
    participant_child = ParticipantFactory(camp=camp, is_child=True, first_name="C", last_name="C")
    participant_companion = ParticipantFactory(camp=camp, is_companion=True, first_name="A", last_name="A")
    participant_adult = ParticipantFactory(camp=camp, first_name="B", last_name="B")

    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        name="Child Drink",
        applies_to_children=True,
        applies_to_adults=False,
        applies_to_companions=False,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        name="Companion Drink",
        applies_to_children=False,
        applies_to_adults=False,
        applies_to_companions=True,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        name="Adult Drink",
        applies_to_children=False,
        applies_to_adults=True,
        applies_to_companions=False,
    )

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant_child.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))
    assert b"Child Drink" in response.content
    assert b"Companion Drink" not in response.content
    assert b"Adult Drink" not in response.content

    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant_companion.pk
    session.save()
    response = kiosk_client.get(reverse("kiosk-home"))
    assert b"Child Drink" not in response.content
    assert b"Companion Drink" in response.content
    assert b"Adult Drink" not in response.content

    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant_adult.pk
    session.save()
    response = kiosk_client.get(reverse("kiosk-home"))
    assert b"Child Drink" not in response.content
    assert b"Companion Drink" not in response.content
    assert b"Adult Drink" in response.content


@pytest.mark.django_db
def test_kiosk_quick_food_tiles_hide_date_specific_meal_rules(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=PriceRule.MealType.BREAKFAST,
        meal_date=None,
        applies_to_children=False,
        applies_to_adults=True,
        name="Standard Frühstück",
        unit_price=Decimal("4.00"),
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=PriceRule.MealType.BREAKFAST,
        meal_date=date(2026, 7, 2),
        applies_to_children=False,
        applies_to_adults=True,
        name="Spezial Frühstück",
        unit_price=Decimal("6.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert "Standard Frühstück".encode() in response.content
    assert "Spezial Frühstück".encode() not in response.content
    assert b'id="food-step-date"' not in response.content
    assert b"data-food-date" not in response.content


@pytest.mark.django_db
def test_kiosk_quick_food_booking_applies_todays_date_specific_breakfast_price(kiosk_client, monkeypatch):
    booking_date = date(2026, 7, 2)
    monkeypatch.setattr("billing.views.timezone.localdate", lambda value=None, timezone=None: booking_date)
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    standard_rule = PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=PriceRule.MealType.BREAKFAST,
        meal_date=None,
        applies_to_children=False,
        applies_to_adults=True,
        name="Standard Frühstück",
        unit_price=Decimal("4.00"),
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=PriceRule.MealType.BREAKFAST,
        meal_date=booking_date,
        applies_to_children=False,
        applies_to_adults=True,
        name="Spezial Frühstück",
        unit_price=Decimal("6.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "quick",
            "quick-price_rule": standard_rule.pk,
            "quick-quantity": 1,
            "quick-quick_date": date(2030, 1, 1).isoformat(),
        },
    )

    assert response.status_code == 302
    charge = Charge.objects.get(participant=participant, kind=Charge.Kind.FOOD)
    assert charge.description == "Spezial Frühstück (Kiosk)"
    assert charge.unit_price == Decimal("6.00")
    assert charge.occurred_on == booking_date


@pytest.mark.django_db
def test_kiosk_meal_signup_child_breakfast_override(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=date(2026, 7, 2))
    participant = ParticipantFactory(camp=camp, first_name="Timmy", is_child=True)

    # Standard price
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.BREAKFAST,
        is_default=True,
        applies_to_children=True,
        applies_to_adults=False,
        name="Standard Frühstück Kind",
        unit_price=Decimal("4.00"),
    )

    # Override price for July 2nd
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.BREAKFAST,
        meal_date=date(2026, 7, 2),
        is_default=False,
        applies_to_children=True,
        applies_to_adults=False,
        name="Besonderes Frühstück",
        unit_price=Decimal("5.50"),
    )

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    # Book standard day
    kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.BREAKFAST,
            "meal-variant": MealSignup.Variant.NORMAL_CHILD,
        },
    )

    # Book override day
    kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 2).isoformat(),
            "meal-meal": MealSignup.Meal.BREAKFAST,
            "meal-variant": MealSignup.Variant.NORMAL_CHILD,
        },
    )

    charges = list(Charge.objects.filter(participant=participant, kind=Charge.Kind.FOOD).order_by("occurred_on"))
    assert len(charges) == 2
    assert charges[0].unit_price == Decimal("4.00")
    assert charges[0].description == "Standard Frühstück Kind Frühstück"
    assert charges[1].unit_price == Decimal("5.50")
    assert charges[1].description == "Besonderes Frühstück Frühstück"


@pytest.mark.django_db
def test_kiosk_offers_breakfast_prebooking_in_meal_calendar(kiosk_client, monkeypatch):
    """Expose future breakfast bookings alongside the existing dinner calendar."""
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    meal_date = date(2026, 7, 1)
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=meal_date)
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.BREAKFAST,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Standard Frühstück",
        unit_price=Decimal("5.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'data-meal-type="breakfast"' in content
    assert "Jetzt buchen" in content
    assert "Für später vorbestellen" in content
    assert 'data-dialog-target="breakfast-meal-calendar"' not in content
    assert 'data-dialog-target="breakfast-meal-dialog"' not in content
    meal_day = next(day for day in response.context["breakfast_calendar_days"] if day["date"] == meal_date)
    breakfast_slot = meal_day["meals"][0]
    assert breakfast_slot["price_rule"].name == "Standard Frühstück"
    assert breakfast_slot["locked"] is False
    assert response.context["dinner_calendar_days"]


@pytest.mark.django_db
def test_kiosk_meal_calendars_keep_slots_descriptions_prices_and_aria_separate(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    meal_date = date(2026, 7, 1)
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.BREAKFAST,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Standard Frühstück",
        unit_price=Decimal("5.00"),
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Standard Abendessen",
        unit_price=Decimal("7.00"),
    )
    MealPlanEntry.objects.create(
        camp=camp,
        meal_date=meal_date,
        meal=MealSignup.Meal.DINNER,
        description="Pasta mit Salat",
    )
    breakfast_signup = MealSignup.objects.create(
        participant=participant,
        meal_date=meal_date,
        meal=MealSignup.Meal.BREAKFAST,
        variant=MealSignup.Variant.NORMAL,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))
    content = response.content.decode()

    dinner_day = next(day for day in response.context["dinner_calendar_days"] if day["date"] == meal_date)
    breakfast_day = next(day for day in response.context["breakfast_calendar_days"] if day["date"] == meal_date)
    assert dinner_day["meals"][0]["description"] == "Pasta mit Salat"
    assert breakfast_day["meals"][0]["description"] == ""
    assert breakfast_day["meals"][0]["price_rule"].name == "Standard Frühstück"
    assert breakfast_day["status"] == "booked"
    assert dinner_day["status"] == "empty"
    assert f'name="meal_signup_id" value="{breakfast_signup.pk}"' in content

    dinner_calendar = content[
        content.index('id="meal-calendar-dialog"') : content.index(
            "</dialog>", content.index('id="meal-calendar-dialog"')
        )
    ]
    breakfast_calendar = content[
        content.index('id="breakfast-meal-calendar"') : content.index(
            "</dialog>", content.index('id="breakfast-meal-calendar"')
        )
    ]
    assert "Pasta mit Salat" in dinner_calendar
    assert "Pasta mit Salat" not in breakfast_calendar
    assert "Standard Frühstück" not in dinner_calendar
    assert "Standard Frühstück" in breakfast_calendar
    assert "Frühstück:" in breakfast_calendar
    assert "Abendessen:" in dinner_calendar
    assert 'aria-label="' in dinner_calendar
    assert 'aria-label="' in breakfast_calendar


@pytest.mark.django_db
def test_kiosk_breakfast_calendar_shows_retracted_status_separately(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    meal_date = date(2026, 7, 1)
    camp = CampFactory(starts_on=meal_date, ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.BREAKFAST,
        is_default=True,
        name="Frühstück",
        unit_price=Decimal("5.00"),
    )
    MealSignup.objects.create(
        participant=participant,
        meal_date=meal_date,
        meal=MealSignup.Meal.BREAKFAST,
        variant=MealSignup.Variant.NORMAL,
        status=MealSignup.Status.RETRACTED,
        retracted_at=timezone.now(),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    breakfast_day = response.context["breakfast_calendar_days"][0]
    dinner_day = response.context["dinner_calendar_days"][0]
    assert breakfast_day["status"] == "retracted"
    assert breakfast_day["status_label"] == "Zurückgenommen"
    assert dinner_day["status"] == "empty"


@pytest.mark.django_db
def test_kiosk_breakfast_booking_without_price_is_rejected(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=date(2026, 7, 2))
    participant = ParticipantFactory(camp=camp)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.BREAKFAST,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert b"kein Preis hinterlegt" in response.content
    assert not MealSignup.objects.filter(participant=participant).exists()
    assert not Charge.objects.filter(participant=participant, kind=Charge.Kind.FOOD).exists()


@pytest.mark.django_db
def test_kiosk_breakfast_booking_rejects_date_outside_camp(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=date(2026, 7, 2))
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.BREAKFAST,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        unit_price=Decimal("5.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 3).isoformat(),
            "meal-meal": MealSignup.Meal.BREAKFAST,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert "keine gültige Auswahl" in response.context["meal_form"].errors["meal_dates"][0]
    assert not MealSignup.objects.filter(participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_duplicate_breakfast_booking_updates_one_signup(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    meal_date = date(2026, 7, 1)
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.BREAKFAST,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        unit_price=Decimal("5.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    payload = {
        "action": "meal",
        "meal-meal_dates": meal_date.isoformat(),
        "meal-meal": MealSignup.Meal.BREAKFAST,
        "meal-variant": MealSignup.Variant.NORMAL,
    }

    assert kiosk_client.post(reverse("kiosk-home"), payload).status_code == 302
    payload["meal-variant"] = MealSignup.Variant.VEGAN
    assert kiosk_client.post(reverse("kiosk-home"), payload).status_code == 302

    signup = MealSignup.objects.get(participant=participant, meal=MealSignup.Meal.BREAKFAST)
    assert signup.variant == MealSignup.Variant.VEGAN
    assert Charge.objects.filter(participant=participant, occurred_on=meal_date, kind=Charge.Kind.FOOD).count() == 1


@pytest.mark.django_db
def test_kiosk_books_breakfast_for_family_member(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    meal_date = date(2026, 7, 1)
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    family_member = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Kind",
        last_name="Muster",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.BREAKFAST,
        is_default=True,
        applies_to_children=True,
        applies_to_adults=False,
        unit_price=Decimal("3.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": meal_date.isoformat(),
            "meal-meal": MealSignup.Meal.BREAKFAST,
            "meal-variant": MealSignup.Variant.NORMAL,
            "meal-target": f"family-{family_member.pk}",
            f"meal-variant-family-{family_member.pk}": MealSignup.Variant.NORMAL_CHILD,
        },
    )

    assert response.status_code == 302
    signup = MealSignup.objects.get(family_member=family_member, meal=MealSignup.Meal.BREAKFAST)
    assert signup.charge is not None
    assert signup.charge.unit_price == Decimal("3.00")


@pytest.mark.django_db
def test_kiosk_breakfast_booking_respects_cutoff(kiosk_client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 6, 30, 13, 0))
    _freeze_meal_lock_time(monkeypatch, fixed_now)
    meal_date = date(2026, 7, 1)
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=meal_date, meal_booking_cutoff_time=time(12, 0))
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.BREAKFAST,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        unit_price=Decimal("5.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": meal_date.isoformat(),
            "meal-meal": MealSignup.Meal.BREAKFAST,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert "Buchungen und Rücknahmen".encode() in response.content
    assert not MealSignup.objects.filter(participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_breakfast_booking_rejects_unknown_target_without_partial_state(kiosk_client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    meal_date = date(2026, 7, 1)
    camp = CampFactory(starts_on=date(2026, 6, 30), ends_on=meal_date)
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.BREAKFAST,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        unit_price=Decimal("5.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": meal_date.isoformat(),
            "meal-meal": MealSignup.Meal.BREAKFAST,
            "meal-variant": MealSignup.Variant.NORMAL,
            "meal-target": "participant-999999",
        },
    )

    assert response.status_code == 200
    assert "nicht verfügbar".encode() in response.content
    assert not MealSignup.objects.filter(participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_meal_signup_without_price_rule_shows_error(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    # intentionally not creating a PriceRule for dinner

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert (
        b"Keine Preisregel f\xc3\xbcr diese Mahlzeit hinterlegt." in response.content
        or b"error" in response.content.lower()
        or b"fehler" in response.content.lower()
    )
    assert not MealSignup.objects.filter(participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_books_snack_successfully(kiosk_client):
    camp = CampFactory()
    participant = ParticipantFactory(
        camp=camp,
        first_name="Ada",
        last_name="Lovelace",
    )
    rule = PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=PriceRule.MealType.SNACK,
        name="Mittagssnack",
        unit_price=Decimal("4.50"),
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
        },
    )

    assert response.status_code == 302
    entry = Charge.objects.get(participant=participant, kind=Charge.Kind.FOOD)
    assert entry.description == "Mittagssnack (Kiosk)"
    assert entry.quantity == Decimal("1.00")
    assert entry.unit_price == Decimal("4.50")


@pytest.mark.django_db
def test_kiosk_show_invoices_setting_toggle(kiosk_client):
    camp = CampFactory(is_active=True, show_kiosk_invoices=False)
    participant = ParticipantFactory(camp=camp)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))
    assert response.status_code == 200
    assert "Meine Rechnungen" not in response.content.decode("utf-8")

    pdf_response = kiosk_client.get(reverse("kiosk-current-settlement-pdf"))
    assert pdf_response.status_code == 403

    camp.show_kiosk_invoices = True
    camp.save()

    response_active = kiosk_client.get(reverse("kiosk-home"))
    assert response_active.status_code == 200
    content = response_active.content.decode("utf-8")
    assert "Meine Rechnungen" in content
    assert 'data-pdf-preview="true"' in content
    assert 'id="global-pdf-dialog"' in content

    pdf_response = kiosk_client.get(reverse("kiosk-current-settlement-pdf"))
    assert pdf_response.status_code == 200
    assert pdf_response["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in pdf_response["Content-Security-Policy"]


@pytest.mark.django_db
def test_kiosk_self_registration_creates_pending_participant(kiosk_client):
    camp = CampFactory(is_active=True)
    response = kiosk_client.post(
        reverse("kiosk-self-register"),
        {
            "first_name": "Lukas",
            "last_name": "Neumann",
            "email": "lukas@example.com",
            "phone": "0170123456",
            "pin": "2468",
            "pin_repeat": "2468",
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("kiosk-login")

    p = Participant.objects.get(camp=camp, first_name="Lukas", last_name="Neumann")
    assert p.status == Participant.Status.PENDING_APPROVAL
    assert p.pin.pin_hash != "2468"
    assert p.pin.check_pin("2468") is True

    # Must NOT be visible in kiosk login dropdown
    login_page = kiosk_client.get(reverse("kiosk-login"))
    assert "Lukas Neumann" not in login_page.content.decode("utf-8")


@pytest.mark.django_db
def test_kiosk_self_registration_rejects_mismatched_pin(kiosk_client):
    camp = CampFactory(is_active=True)

    response = kiosk_client.post(
        reverse("kiosk-self-register"),
        {
            "first_name": "Lukas",
            "last_name": "Neumann",
            "pin": "2468",
            "pin_repeat": "8642",
        },
    )

    assert response.status_code == 400
    assert b"Die PINs stimmen nicht \xc3\xbcberein." in response.content
    assert b'id="self-registration-dialog" open' in response.content
    assert response.content.count(b'id="id_pin"') == 1
    assert b'for="id_enrollment_pin"' in response.content
    assert b'id="id_enrollment_pin"' in response.content
    assert not Participant.objects.filter(camp=camp, first_name="Lukas", last_name="Neumann").exists()


@pytest.mark.django_db
def test_kiosk_self_registration_rejects_trivial_pins(kiosk_client):
    camp = CampFactory(is_active=True)

    for trivial_pin in ["0000", "1111", "1234", "4321"]:
        response = kiosk_client.post(
            reverse("kiosk-self-register"),
            {
                "first_name": "Lukas",
                "last_name": "Neumann",
                "pin": trivial_pin,
                "pin_repeat": trivial_pin,
            },
        )
        assert response.status_code == 400
        assert "sicherere PIN" in response.content.decode("utf-8")
        assert not Participant.objects.filter(camp=camp, first_name="Lukas", last_name="Neumann").exists()


@pytest.mark.django_db
def test_kiosk_self_registration_allows_dates_within_4_day_buffer(kiosk_client):
    camp = CampFactory(
        is_active=True,
        starts_on=date(2026, 8, 10),
        ends_on=date(2026, 8, 20),
    )
    response = kiosk_client.post(
        reverse("kiosk-self-register"),
        {
            "first_name": "Lukas",
            "last_name": "Neumann",
            "arrival_date": "2026-08-07",  # 3 days before start (within 4-day buffer)
            "departure_date": "2026-08-23",  # 3 days after end (within 4-day buffer)
            "pin": "2468",
            "pin_repeat": "2468",
        },
    )
    assert response.status_code == 302
    p = Participant.objects.get(camp=camp, first_name="Lukas", last_name="Neumann")
    assert p.arrival_date == date(2026, 8, 7)
    assert p.departure_date == date(2026, 8, 23)


@pytest.mark.django_db
def test_kiosk_self_registration_rejects_dates_outside_4_day_buffer(kiosk_client):
    CampFactory(
        is_active=True,
        starts_on=date(2026, 8, 10),
        ends_on=date(2026, 8, 20),
    )
    # Arrival 5 days before start
    resp_early = kiosk_client.post(
        reverse("kiosk-self-register"),
        {
            "first_name": "Anna",
            "last_name": "Meier",
            "arrival_date": "2026-08-05",
            "departure_date": "2026-08-15",
            "pin": "2468",
            "pin_repeat": "2468",
        },
    )
    assert resp_early.status_code == 400
    assert "maximal 4 Tage (halbe Woche) vor Lagerbeginn" in resp_early.content.decode("utf-8")

    # Departure 5 days after end
    resp_late = kiosk_client.post(
        reverse("kiosk-self-register"),
        {
            "first_name": "Ben",
            "last_name": "Schulz",
            "arrival_date": "2026-08-10",
            "departure_date": "2026-08-26",
            "pin": "2468",
            "pin_repeat": "2468",
        },
    )
    assert resp_late.status_code == 400
    assert "maximal 4 Tage (halbe Woche) nach Lagerende" in resp_late.content.decode("utf-8")

    # Departure before arrival
    resp_invalid_order = kiosk_client.post(
        reverse("kiosk-self-register"),
        {
            "first_name": "Clara",
            "last_name": "Weber",
            "arrival_date": "2026-08-15",
            "departure_date": "2026-08-12",
            "pin": "2468",
            "pin_repeat": "2468",
        },
    )
    assert resp_invalid_order.status_code == 400
    assert "Die Abreise muss nach der Anreise liegen" in resp_invalid_order.content.decode("utf-8")


@pytest.mark.django_db
def test_kiosk_self_registration_renders_wizard_steps_and_min_max(kiosk_client):
    CampFactory(
        is_active=True,
        starts_on=date(2026, 8, 10),
        ends_on=date(2026, 8, 20),
    )
    response = kiosk_client.get(reverse("kiosk-login"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "wizard-dialog" in content
    assert 'data-wizard-step="1"' in content
    assert 'data-wizard-step="4"' in content
    assert 'min="2026-08-06"' in content  # 10th minus 4 days
    assert 'max="2026-08-24"' in content  # 20th plus 4 days
    assert "Hinweis zur Frühanreise" in content


@pytest.mark.django_db
def test_kiosk_self_registration_is_persistently_rate_limited(kiosk_client, settings):
    CampFactory(is_active=True)
    settings.KIOSK_REGISTRATION_MAX_ATTEMPTS = 2
    settings.KIOSK_REGISTRATION_ATTEMPT_WINDOW = 900

    for index in range(2):
        response = kiosk_client.post(
            reverse("kiosk-self-register"),
            {
                "first_name": f"Teilnehmer{index}",
                "last_name": "Neumann",
                "pin": "2468",
                "pin_repeat": "2468",
            },
            REMOTE_ADDR="192.0.2.10",
        )
        assert response.status_code == 302

    session_cookie_name = settings.SESSION_COOKIE_NAME
    kiosk_client.cookies.pop(session_cookie_name, None)
    blocked_response = kiosk_client.post(
        reverse("kiosk-self-register"),
        {
            "first_name": "Teilnehmer2",
            "last_name": "Neumann",
            "pin": "2468",
            "pin_repeat": "2468",
        },
        REMOTE_ADDR="192.0.2.10",
    )

    assert blocked_response.status_code == 429
    assert blocked_response["Retry-After"] == "900"
    assert b"Zu viele Registrierungsversuche" in blocked_response.content
    assert Participant.objects.count() == 2


@pytest.mark.django_db
def test_admin_approval_requires_pin_and_explicit_price_attribute_confirmation(kiosk_client):
    admin_user = UserFactory(is_staff=True, is_superuser=True)
    kiosk_client.force_login(admin_user)
    camp = CampFactory(is_active=True)
    p = ParticipantFactory(
        camp=camp, first_name="Clara", last_name="Müller", status=Participant.Status.PENDING_APPROVAL
    )

    detail_response = kiosk_client.get(reverse("camp-detail", kwargs={"camp_id": camp.pk}))
    detail_content = detail_response.content.decode("utf-8")
    assert detail_response.status_code == 200
    assert f'id="approval-{p.pk}-confirmed"' in detail_content
    assert "Preisrelevante Angaben geprüft" in detail_content
    assert f'id="approval-{p.pk}-hilfssatz"' in detail_content
    assert f'id="approval-{p.pk}-berufssatz"' in detail_content
    assert "Nur bei Jugendgruppe erforderlich" in detail_content
    assert 'class="responsive-record-table pending-registration-table"' in detail_content
    assert 'data-label="Aktionen"' in detail_content
    assert "PIN fehlt – Freigabe ist gesperrt" in detail_content

    response = kiosk_client.post(
        reverse("participant-approve-registration", kwargs={"camp_id": camp.pk, "participant_id": p.pk}),
        {
            "is_child": "on",
            "is_youth_group": "on",
            "hilfssatz": "0.5000",
            "berufssatz": "0.3300",
            "price_attributes_confirmed": "on",
        },
    )

    assert response.status_code == 302
    p.refresh_from_db()
    assert p.status == Participant.Status.PENDING_APPROVAL

    p.pin.set_pin("2468")
    p.pin.save()
    response = kiosk_client.post(
        reverse("participant-approve-registration", kwargs={"camp_id": camp.pk, "participant_id": p.pk}),
        {
            "is_child": "on",
            "is_youth_group": "on",
        },
    )

    assert response.status_code == 302
    p.refresh_from_db()
    assert p.status == Participant.Status.PENDING_APPROVAL

    response = kiosk_client.post(
        reverse("participant-approve-registration", kwargs={"camp_id": camp.pk, "participant_id": p.pk}),
        {
            "is_child": "on",
            "is_youth_group": "on",
            "hilfssatz": "0.5000",
            "berufssatz": "0.3300",
            "price_attributes_confirmed": "on",
        },
    )

    assert response.status_code == 302
    p.refresh_from_db()
    assert p.status == Participant.Status.REGISTERED
    assert p.is_child is True
    assert p.is_youth_group is True
    assert p.is_companion is False
    assert p.hilfssatz == Decimal("0.5000")
    assert p.berufssatz == Decimal("0.3300")

    # Now visible in kiosk login dropdown
    login_page = kiosk_client.get(reverse("kiosk-login"))
    assert "Clara Müller" in login_page.content.decode("utf-8")


@pytest.mark.django_db
def test_admin_rejects_self_registration(kiosk_client):
    admin_user = UserFactory(is_staff=True, is_superuser=True)
    kiosk_client.force_login(admin_user)
    camp = CampFactory(is_active=True)
    p = ParticipantFactory(camp=camp, first_name="Tim", last_name="Test", status=Participant.Status.PENDING_APPROVAL)

    # Reject
    response = kiosk_client.post(
        reverse("participant-reject-registration", kwargs={"camp_id": camp.pk, "participant_id": p.pk})
    )
    assert response.status_code == 302
    assert not Participant.objects.filter(pk=p.pk).exists()


@pytest.mark.django_db
def test_admin_cannot_reject_registered_participant_through_registration_action(kiosk_client):
    admin_user = UserFactory(is_staff=True, is_superuser=True)
    kiosk_client.force_login(admin_user)
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp, status=Participant.Status.REGISTERED)

    response = kiosk_client.post(
        reverse(
            "participant-reject-registration",
            kwargs={"camp_id": camp.pk, "participant_id": participant.pk},
        )
    )

    assert response.status_code == 404
    assert Participant.objects.filter(pk=participant.pk).exists()


@pytest.mark.django_db
def test_kiosk_donation_creates_charge(kiosk_client):
    from decimal import Decimal

    from django.urls import reverse

    from billing.models import Charge
    from billing.views import KIOSK_PARTICIPANT_SESSION_KEY
    from tests.factories import CampFactory, ParticipantFactory

    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "donate",
            "donation_amount": "15,50",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("kiosk-home")

    charge = Charge.objects.filter(participant=participant, kind=Charge.Kind.DONATION).last()
    assert charge is not None
    assert charge.unit_price == Decimal("15.50")
    assert charge.kiosk_booked_by == participant


@pytest.mark.django_db
def test_kiosk_donation_invalid_amount(kiosk_client):
    from django.urls import reverse

    from billing.models import Charge
    from billing.views import KIOSK_PARTICIPANT_SESSION_KEY
    from tests.factories import CampFactory, ParticipantFactory

    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {"action": "donate", "donation_amount": "-5"},
    )

    assert response.status_code == 302
    assert not Charge.objects.filter(participant=participant, kind=Charge.Kind.DONATION).exists()
