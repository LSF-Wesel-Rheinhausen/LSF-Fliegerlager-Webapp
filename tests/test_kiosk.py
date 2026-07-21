from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from billing.models import (
    Charge,
    Expense,
    MealOrder,
    MealPlanEntry,
    MealSignup,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    Payment,
    PriceRule,
    UserProfile,
)
from billing.services import create_settlement_run
from billing.views import (
    KIOSK_FAMILY_MEMBER_SESSION_KEY,
    KIOSK_PARTICIPANT_SESSION_KEY,
    KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY,
    KIOSK_PIN_SETUP_SESSION_KEY,
)
from tests.factories import CampFactory, ExpenseFactory, ParticipantFactory, PriceRuleFactory, UserFactory


def _freeze_meal_lock_time(monkeypatch, fixed_now):
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())


@pytest.mark.django_db
def test_kiosk_login_rejects_empty_participant_placeholder(client):
    response = client.post(reverse("kiosk-login"), {"participant": "", "pin": "1234"})

    assert response.status_code == 200
    assert "participant" in response.context["form"].errors
    assert KIOSK_PARTICIPANT_SESSION_KEY not in client.session
    assert KIOSK_PIN_SETUP_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_kiosk_login_redirects_to_pin_setup_when_pin_is_missing(client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")

    response = client.post(reverse("kiosk-login"), {"participant": f"participant-{participant.pk}", "pin": "1234"})

    assert response.status_code == 302
    assert response["Location"] == reverse("kiosk-pin-setup")
    assert client.session[KIOSK_PIN_SETUP_SESSION_KEY] == participant.pk
    assert KIOSK_PARTICIPANT_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_kiosk_pin_setup_sets_pin_and_logs_participant_in(client, settings):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PIN_SETUP_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
        reverse("kiosk-pin-setup"),
        {"pin": "2468", "pin_repeat": "2468"},
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("kiosk-home")
    participant.refresh_from_db()
    assert participant.pin.check_pin("2468") is True
    assert client.session[KIOSK_PARTICIPANT_SESSION_KEY] == participant.pk
    assert KIOSK_PIN_SETUP_SESSION_KEY not in client.session
    assert client.session.get_expire_at_browser_close() is False
    assert client.session.get_expiry_age() == settings.SESSION_COOKIE_AGE


@pytest.mark.django_db
def test_kiosk_login_redirects_companion_to_pin_setup_when_pin_is_missing(client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )

    response = client.post(reverse("kiosk-login"), {"participant": f"family-{companion.pk}", "pin": "1234"})

    assert response.status_code == 302
    assert response["Location"] == reverse("kiosk-pin-setup")
    assert client.session[KIOSK_PIN_SETUP_SESSION_KEY] == participant.pk
    assert client.session[KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY] == companion.pk
    assert KIOSK_PARTICIPANT_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_kiosk_pin_setup_sets_companion_pin_and_logs_guardian_in(client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    session = client.session
    session[KIOSK_PIN_SETUP_SESSION_KEY] = participant.pk
    session[KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY] = companion.pk
    session.save()

    response = client.post(
        reverse("kiosk-pin-setup"),
        {"pin": "2468", "pin_repeat": "2468"},
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("kiosk-home")
    companion.pin.refresh_from_db()
    assert companion.pin.check_pin("2468") is True
    assert client.session[KIOSK_PARTICIPANT_SESSION_KEY] == participant.pk
    assert client.session[KIOSK_FAMILY_MEMBER_SESSION_KEY] == companion.pk
    assert KIOSK_PIN_SETUP_SESSION_KEY not in client.session
    assert KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_kiosk_login_accepts_companion_pin_and_uses_guardian_session(client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    companion.pin.set_pin("1234")
    companion.pin.save()

    response = client.post(reverse("kiosk-login"), {"participant": f"family-{companion.pk}", "pin": "1234"})

    assert response.status_code == 302
    assert response["Location"] == reverse("kiosk-home")
    assert client.session[KIOSK_PARTICIPANT_SESSION_KEY] == participant.pk
    assert client.session[KIOSK_FAMILY_MEMBER_SESSION_KEY] == companion.pk


@pytest.mark.django_db
def test_kiosk_login_rejects_invalid_pin_for_existing_pin(client):
    participant = ParticipantFactory(first_name="Grace", last_name="Hopper")
    participant.pin.set_pin("1234")
    participant.pin.save()

    response = client.post(reverse("kiosk-login"), {"participant": f"participant-{participant.pk}", "pin": "9999"})

    assert response.status_code == 200
    assert KIOSK_PARTICIPANT_SESSION_KEY not in client.session
    assert KIOSK_PIN_SETUP_SESSION_KEY not in client.session
    assert b"Teilnehmer oder PIN ist ung\xc3\xbcltig." in response.content


@pytest.mark.django_db
def test_kiosk_login_locks_pin_after_repeated_failures(client):
    participant = ParticipantFactory(first_name="Grace", last_name="Hopper")
    participant.pin.set_pin("1234")
    participant.pin.save()

    for _ in range(participant.pin.MAX_FAILED_ATTEMPTS):
        client.post(reverse("kiosk-login"), {"participant": f"participant-{participant.pk}", "pin": "9999"})

    participant.pin.refresh_from_db()
    response = client.post(reverse("kiosk-login"), {"participant": f"participant-{participant.pk}", "pin": "1234"})

    assert participant.pin.is_locked is True
    assert response.status_code == 200
    assert b"Zu viele Fehlversuche" in response.content
    assert KIOSK_PARTICIPANT_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_kiosk_login_links_to_admin_interface(client):
    response = client.get(reverse("kiosk-login"))

    assert response.status_code == 200
    assert reverse("login").encode() in response.content
    assert b"Admin-Interface" in response.content
    content = response.content.decode()
    assert content.index("Teilnehmer auswählen") < content.index("Neu hier?")


@pytest.mark.django_db
def test_kiosk_home_hides_normal_admin_header_and_renders_drink_dialog_controls(client):
    user = UserFactory(username="admin", email="admin@example.test")
    client.force_login(user)

    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.DRINK,
        name="Getränk",
        unit_price=Decimal("2.50"),
        is_default=True,
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

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
    assert b"Brutto:" not in response.content
    assert b"Soll:" not in response.content


@pytest.mark.django_db
def test_kiosk_checkin_updates_own_and_linked_participant_dates(client):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    linked = ParticipantFactory(camp=camp, first_name="Grace", last_name="B")
    ParticipantBookingLink.objects.create(
        inviter=participant,
        invitee=linked,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [f"participant-{participant.pk}", f"participant-{linked.pk}"],
            f"arrival_date_participant-{participant.pk}": "2026-07-02",
            f"departure_date_participant-{participant.pk}": "2026-07-10",
            f"arrival_date_participant-{linked.pk}": "2026-07-03",
            f"departure_date_participant-{linked.pk}": "2026-07-09",
        },
    )

    assert response.status_code == 302
    participant.refresh_from_db()
    linked.refresh_from_db()
    assert participant.arrival_date == date(2026, 7, 2)
    assert participant.departure_date == date(2026, 7, 10)
    assert participant.booked_nights == 8
    assert linked.arrival_date == date(2026, 7, 3)
    assert linked.departure_date == date(2026, 7, 9)
    assert linked.booked_nights == 6


@pytest.mark.django_db
def test_kiosk_checkin_rejects_unlinked_participant(client):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    unlinked = ParticipantFactory(camp=camp, first_name="Grace", last_name="B")
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_checkin_rejects_departure_before_arrival(client):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [f"participant-{participant.pk}"],
            f"arrival_date_participant-{participant.pk}": "2026-07-10",
            f"departure_date_participant-{participant.pk}": "2026-07-02",
        },
    )

    assert response.status_code == 200
    participant.refresh_from_db()
    assert participant.arrival_date is None
    assert participant.departure_date is None
    assert "Die Abreise für Ada A muss nach der Anreise liegen.".encode() in response.content


@pytest.mark.django_db
def test_kiosk_checkin_updates_companion_and_rejects_child_target(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [f"family-{companion.pk}", f"family-{child.pk}"],
            f"arrival_date_family-{companion.pk}": "2026-07-02",
            f"departure_date_family-{companion.pk}": "2026-07-10",
            f"arrival_date_family-{child.pk}": "2026-07-03",
            f"departure_date_family-{child.pk}": "2026-07-09",
        },
    )

    assert response.status_code == 200
    companion.refresh_from_db()
    child.refresh_from_db()
    assert companion.arrival_date is None
    assert companion.departure_date is None
    assert child.arrival_date is None
    assert child.departure_date is None
    assert "Ein Teilnehmer darf über diesen Kiosk nicht bearbeitet werden.".encode() in response.content

    response = client.post(
        reverse("kiosk-home"),
        {
            "action": "checkin",
            "checkin_target": [f"family-{companion.pk}"],
            f"arrival_date_family-{companion.pk}": "2026-07-02",
            f"departure_date_family-{companion.pk}": "2026-07-10",
        },
    )

    assert response.status_code == 302
    companion.refresh_from_db()
    assert companion.arrival_date == date(2026, 7, 2)
    assert companion.departure_date == date(2026, 7, 10)


@pytest.mark.django_db
def test_kiosk_home_checkin_dialog_lists_companion_but_not_child(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode()
    checkin_dialog = content[content.index('id="checkin-dialog"') :]
    assert "Grace A" in checkin_dialog
    assert "Kind A" not in checkin_dialog


@pytest.mark.django_db
def test_kiosk_home_shows_leadership_contact_button(client):
    camp = CampFactory()
    admin_user = UserFactory(username="leitung", email="leitung@example.test")
    admin_user.is_superuser = True
    admin_user.save()
    UserProfile.objects.create(user=admin_user, phone="0123 / 456")
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"Kontakt Lagerleitung" in response.content
    assert response.content.count(b"Kontakt Lagerleitung") == 2
    assert b"leitung@example.test" in response.content
    assert b'href="tel:0123456"' in response.content
    assert b"0123 / 456" in response.content


@pytest.mark.django_db
def test_kiosk_home_renders_balance_with_correct_signs(client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    Payment.objects.create(participant=participant, amount=Decimal("15.00"), paid_on=date(2026, 7, 1))
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"+15,00 \xe2\x82\xac" in response.content


@pytest.mark.django_db
def test_kiosk_shared_expense_upload_shows_receipt_link_and_serves_file(client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    receipt = SimpleUploadedFile("rechnung.pdf", b"test receipt", content_type="application/pdf")
    response = client.post(
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
        home_response = client.get(reverse("kiosk-home"))
        assert home_response.status_code == 200
        assert b"Beleg" in home_response.content
        assert receipt_url.encode() in home_response.content

        assert Path(expense.receipt.path).exists()
        file_response = client.get(receipt_url)
        assert file_response.status_code == 200
        assert b"".join(file_response.streaming_content) == b"test receipt"
    finally:
        expense.receipt.delete(save=False)


@pytest.mark.django_db
def test_kiosk_shared_expense_upload_rejects_unsupported_receipt_type(client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    receipt = SimpleUploadedFile("rechnung.txt", b"not a receipt", content_type="text/plain")
    response = client.post(
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
def test_kiosk_shared_expense_upload_rejects_oversized_receipt(client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    receipt = SimpleUploadedFile("rechnung.pdf", b"x" * (5 * 1024 * 1024 + 1), content_type="application/pdf")
    response = client.post(
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
def test_kiosk_expense_receipt_rejects_other_participants(client):
    camp = CampFactory()
    viewer = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    owner = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    expense = ExpenseFactory(
        participant=owner,
        camp=camp,
        description="Fremder Beleg",
        receipt=SimpleUploadedFile("fremd.pdf", b"private receipt", content_type="application/pdf"),
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = viewer.pk
    session.save()

    try:
        response = client.get(reverse("expense-receipt", args=[expense.pk]))

        assert response.status_code == 403
    finally:
        expense.receipt.delete(save=False)


@pytest.mark.django_db
def test_kiosk_home_marks_rejected_shared_expenses_and_uses_single_contact_entrypoint(client):
    camp = CampFactory()
    admin_user = UserFactory(username="leitung", email="leitung@example.test")
    admin_user.is_superuser = True
    admin_user.save()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    ExpenseFactory(
        participant=participant,
        camp=camp,
        description="Grillgut",
        amount=Decimal("42.00"),
        status=Expense.Status.REJECTED,
        rejection_reason="Beleg fehlt",
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"kiosk-table__row--rejected" in response.content
    assert b"kiosk-status-text kiosk-status-text--danger" in response.content
    assert b"Abgelehnt" in response.content
    assert b"Kontakt anzeigen" not in response.content
    assert response.content.count(b"data-open-contact-dialog>Kontakt Lagerleitung</button>") == 1


@pytest.mark.django_db
def test_kiosk_home_shows_order_sent_for_next_day(client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 18, 30))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(meal_booking_cutoff_time=time(12, 0))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    MealOrder.objects.create(camp=camp, meal_date=date(2026, 7, 2))
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"Die Bestellung wurde abgeschickt." in response.content


@pytest.mark.django_db
def test_kiosk_home_shows_meal_booking_cutoff_time_before_order_sent(client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 10, 30))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(meal_booking_cutoff_time=time(14, 45))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"Die Buchung ist bis 14:45 Uhr m\xc3\xb6glich." in response.content


@pytest.mark.django_db
def test_kiosk_meal_calendar_renders_all_camp_days_with_menu_and_participant_price(client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 6, 30, 10, 0))
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
    MealPlanEntry.objects.create(
        camp=camp,
        meal_date=date(2026, 7, 2),
        meal=MealSignup.Meal.DINNER,
        description="Pasta mit Salat",
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-meal-date="2026-07-01"' in content
    assert 'data-meal-date="2026-07-02"' in content
    assert 'data-meal-date="2026-07-03"' in content
    assert "Pasta mit Salat" in content
    assert "Menü" in content
    assert "7,00 €" in content


@pytest.mark.django_db
def test_kiosk_meal_calendar_shows_closed_days_without_booking_action(client, monkeypatch):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Geschlossen" in content
    assert "Nicht auswählbar" in content
    assert "Buchungen und Rücknahmen für 01.07.2026 sind geschlossen." in content
    assert 'data-meal-date="2026-07-01"' not in content
    assert 'data-meal-date="2026-07-03"' in content


@pytest.mark.django_db
def test_kiosk_home_shows_contact_hint_after_cutoff_before_order_sent(client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 18, 30))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    monkeypatch.setattr("billing.services.timezone.localdate", lambda value=None, timezone=None: fixed_now.date())
    camp = CampFactory(meal_booking_cutoff_time=time(12, 0))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode()
    meal_section_start = content.index("Kalender")
    assert "melde dich bitte bei der Lagerleitung" in content[meal_section_start:]
    status_start = content.index("Die Buchung ist geschlossen.")
    calendar_start = content.index('<div class="meal-status-calendar"')
    assert meal_section_start < status_start < calendar_start


@pytest.mark.django_db
def test_kiosk_meal_status_calendar_shows_day_states_and_detail_dialog(client, monkeypatch):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

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


@pytest.mark.django_db
def test_kiosk_meal_booking_dialog_shows_all_camp_days_with_prices(client, monkeypatch):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

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
def test_kiosk_meal_booking_dialog_keeps_child_only_price_day_selectable(client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 7, 1, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 7, 2), ends_on=date(2026, 7, 2))
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    content = response.content.decode()
    assert response.status_code == 200
    assert 'data-meal-date="2026-07-02"' in content
    assert "Kinder-Abendessen" in content
    assert "4,00 €" in content


@pytest.mark.django_db
def test_private_kiosk_pin_setup_does_not_use_inactivity_logout_timer(client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PIN_SETUP_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-pin-setup"))

    assert response.status_code == 200
    assert b'data-timeout-ms="120000"' not in response.content
    assert reverse("kiosk-logout").encode() in response.content


@pytest.mark.django_db
def test_kiosk_books_drink_with_camp_drink_price_and_subsidy_flag(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_can_cancel_own_quick_booking_within_cancel_window(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 302
    charge.refresh_from_db()
    assert charge.deleted_at is not None
    assert charge.deleted_by is None


@pytest.mark.django_db
def test_kiosk_rejects_quick_booking_cancel_after_cancel_window(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 200
    charge.refresh_from_db()
    assert charge.deleted_at is None


@pytest.mark.django_db
def test_kiosk_rejects_quick_booking_cancel_after_settlement_run_covers_charge(client):
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
    create_settlement_run(camp, UserFactory())
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 200
    charge.refresh_from_db()
    assert charge.deleted_at is None


@pytest.mark.django_db
def test_kiosk_allows_future_quick_booking_cancel_after_earlier_settlement_run(client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    charge = Charge.objects.create(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Frühstück (Kiosk)",
        quantity=Decimal("1.00"),
        unit_price=Decimal("4.00"),
        occurred_on=timezone.localdate() + timedelta(days=1),
        kiosk_booked_by=participant,
    )
    create_settlement_run(camp, UserFactory())
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 302
    charge.refresh_from_db()
    assert charge.deleted_at is not None


@pytest.mark.django_db
def test_kiosk_rejects_quick_booking_cancel_for_unrelated_participant(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 200
    charge.refresh_from_db()
    assert charge.deleted_at is None


@pytest.mark.django_db
def test_kiosk_linked_quick_booking_can_be_cancelled_by_booking_participant(client):
    camp = CampFactory()
    booker = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    linked = ParticipantFactory(camp=camp, first_name="Grace", last_name="Hopper")
    ParticipantBookingLink.objects.create(
        inviter=booker,
        invitee=linked,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )
    PriceRuleFactory(camp=camp, kind=PriceRule.Kind.DRINK, name="Wasser", unit_price=Decimal("1.50"))
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = booker.pk
    session.save()
    client.post(
        reverse("kiosk-home"),
        {
            "action": "quick",
            "quick-price_rule": PriceRule.objects.get(camp=camp, kind=PriceRule.Kind.DRINK).pk,
            "quick-quantity": 1,
            "quick-target": [f"participant-{linked.pk}"],
        },
    )
    charge = Charge.objects.get(participant=linked, kind=Charge.Kind.DRINK)

    response = client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 302
    charge.refresh_from_db()
    assert charge.kiosk_booked_by == booker
    assert charge.deleted_at is not None


@pytest.mark.django_db
def test_kiosk_billed_linked_participant_can_cancel_own_quick_booking(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = linked.pk
    session.save()

    response = client.post(reverse("kiosk-home"), {"action": "quick_cancel", "charge_id": charge.pk})

    assert response.status_code == 302
    charge.refresh_from_db()
    assert charge.deleted_at is not None


@pytest.mark.django_db
def test_kiosk_home_shows_quick_booking_cancel_action(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Letzte Schnellbuchungen" in content
    assert "quick_cancel" in content
    assert "Stornieren" in content
    assert 'class="quick-booking-list"' in content
    assert "data-open-quick-cancel-dialog" in content
    assert 'id="quick-cancel-dialog"' in content


@pytest.mark.django_db
def test_kiosk_home_filters_quick_booking_list_to_kiosk_created_charges(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert f'data-charge-id="{quick_charge.pk}"' in content
    assert content.count('name="action" value="quick_cancel"') == 1


@pytest.mark.django_db
def test_kiosk_meal_signup_updates_existing_signup_and_creates_charge(client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
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
        foerdersatz=Decimal("0"),
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    payload = {
        "action": "meal",
        "meal-meal_dates": date(2026, 7, 1).isoformat(),
        "meal-meal": MealSignup.Meal.DINNER,
        "meal-variant": MealSignup.Variant.NORMAL,
    }
    client.post(reverse("kiosk-home"), payload)
    payload["meal-variant"] = MealSignup.Variant.VEGAN
    response = client.post(reverse("kiosk-home"), payload)

    assert response.status_code == 302
    signup = MealSignup.objects.get(participant=participant)
    assert signup.variant == MealSignup.Variant.VEGAN
    charge = Charge.objects.get(participant=participant, kind=Charge.Kind.FOOD)
    assert charge.description == "Abendessen Abendessen"
    assert charge.unit_price == Decimal("7.00")
    assert signup.charge == charge


@pytest.mark.django_db
def test_kiosk_meal_signup_uses_date_specific_price_only_for_matching_date(client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory()
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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

    response = client.post(
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
def test_kiosk_books_multiple_meal_dates_and_targets_atomically(client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    first_date = date(2026, 7, 1)
    second_date = date(2026, 7, 2)
    camp = CampFactory(starts_on=first_date, ends_on=second_date)
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
    assert response["Location"] == f"{reverse('kiosk-home')}#meal-calendar"
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
def test_kiosk_rejects_entire_meal_batch_when_one_date_has_no_price(client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    first_date = date(2026, 7, 1)
    second_date = date(2026, 7, 2)
    camp = CampFactory(starts_on=first_date, ends_on=second_date)
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_rejects_entire_meal_batch_when_one_date_is_locked(client, monkeypatch):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_normalizes_duplicate_meal_dates(client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    meal_date = date(2026, 7, 1)
    camp = CampFactory(starts_on=meal_date, ends_on=meal_date)
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_rejects_meal_date_outside_configured_camp(client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 2))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_rejects_unknown_meal_target_without_partial_booking(client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    meal_date = date(2026, 7, 1)
    camp = CampFactory(starts_on=meal_date, ends_on=meal_date)
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_meal_signup_for_tomorrow_closes_after_camp_cutoff(client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 12, 1))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    camp = CampFactory(meal_booking_cutoff_time=time(12, 0))
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_meal_signup_for_tomorrow_stays_open_before_camp_cutoff(client, monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 11, 59))
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    camp = CampFactory(meal_booking_cutoff_time=time(12, 0))
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_meal_signup_for_past_date_is_locked(client, monkeypatch):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_meal_signup_for_today_is_locked(client, monkeypatch):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_retracts_meal_signup_and_soft_deletes_food_charge(client, monkeypatch):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(reverse("kiosk-home"), {"action": "meal_retract", "meal_signup_id": signup.pk})

    assert response.status_code == 302
    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.status == MealSignup.Status.RETRACTED
    assert signup.retracted_at is not None
    assert charge.deleted_at is not None


@pytest.mark.django_db
def test_kiosk_rejects_retraction_for_past_meal_signup(client, monkeypatch):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(reverse("kiosk-home"), {"action": "meal_retract", "meal_signup_id": signup.pk})

    assert response.status_code == 200
    assert b"Buchungen und R\xc3\xbccknahmen" in response.content
    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.status == MealSignup.Status.ACTIVE
    assert signup.retracted_at is None
    assert charge.deleted_at is None


@pytest.mark.django_db
def test_kiosk_rejects_retraction_for_today_meal_signup(client, monkeypatch):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(reverse("kiosk-home"), {"action": "meal_retract", "meal_signup_id": signup.pk})

    assert response.status_code == 200
    signup.refresh_from_db()
    charge.refresh_from_db()
    assert signup.status == MealSignup.Status.ACTIVE
    assert signup.retracted_at is None
    assert charge.deleted_at is None


@pytest.mark.django_db
def test_kiosk_meal_signup_requires_person_when_dialog_selection_is_empty(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_creates_family_member_and_books_meal_on_guardian(client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory()
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
        reverse("kiosk-home"),
        {
            "action": "family_member_create",
            "family-first_name": "Kind",
            "family-last_name": "Muster",
            "family-role": ParticipantFamilyMember.Role.CHILD,
        },
    )

    assert response.status_code == 302
    family_member = ParticipantFamilyMember.objects.get(guardian=participant)

    response = client.post(
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


@pytest.mark.django_db
def test_kiosk_booking_link_invite_accept_revoke_flow(client):
    camp = CampFactory()
    inviter = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    invitee = ParticipantFactory(camp=camp, first_name="Grace", last_name="B")
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = inviter.pk
    session.save()

    response = client.post(
        reverse("kiosk-home"),
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
    response = client.post(
        reverse("kiosk-home"),
        {
            "action": "booking_link_accept",
            "booking_link_id": link.pk,
        },
    )

    assert response.status_code == 302
    link.refresh_from_db()
    assert link.status == ParticipantBookingLink.Status.ACCEPTED
    response = client.get(reverse("kiosk-home"))
    assert f"participant-{inviter.pk}".encode() in response.content

    response = client.post(
        reverse("kiosk-home"),
        {
            "action": "booking_link_revoke",
            "booking_link_id": link.pk,
        },
    )

    assert response.status_code == 302
    link.refresh_from_db()
    assert link.status == ParticipantBookingLink.Status.REVOKED


@pytest.mark.django_db
def test_kiosk_books_meal_for_linked_participant_on_linked_account(client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory()
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = inviter.pk
    session.save()

    response = client.post(
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
def test_kiosk_hides_linked_participant_family_member_meal_signups(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = viewer.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert b"Grace B" in response.content
    assert b"Kind B" not in response.content


@pytest.mark.django_db
def test_kiosk_drink_form_filters_by_participant_type(client):
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

    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant_child.pk
    session.save()

    response = client.get(reverse("kiosk-home"))
    assert b"Child Drink" in response.content
    assert b"Companion Drink" not in response.content
    assert b"Adult Drink" not in response.content

    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant_companion.pk
    session.save()
    response = client.get(reverse("kiosk-home"))
    assert b"Child Drink" not in response.content
    assert b"Companion Drink" in response.content
    assert b"Adult Drink" not in response.content

    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant_adult.pk
    session.save()
    response = client.get(reverse("kiosk-home"))
    assert b"Child Drink" not in response.content
    assert b"Companion Drink" not in response.content
    assert b"Adult Drink" in response.content


@pytest.mark.django_db
def test_kiosk_quick_food_tiles_hide_date_specific_meal_rules(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert "Standard Frühstück".encode() in response.content
    assert "Spezial Frühstück".encode() not in response.content
    assert b'id="food-step-date"' not in response.content
    assert b"data-food-date" not in response.content


@pytest.mark.django_db
def test_kiosk_quick_food_booking_applies_todays_date_specific_breakfast_price(client, monkeypatch):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_meal_signup_child_breakfast_override(client, monkeypatch):
    _freeze_meal_lock_time(monkeypatch, timezone.make_aware(datetime(2026, 6, 30, 10, 0)))
    camp = CampFactory()
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

    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    # Book standard day
    client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": date(2026, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.BREAKFAST,
            "meal-variant": MealSignup.Variant.NORMAL_CHILD,
        },
    )

    # Book override day
    client.post(
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
def test_kiosk_pin_setup_rejects_mismatched_pins(client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PIN_SETUP_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
        reverse("kiosk-pin-setup"),
        {"pin": "1234", "pin_repeat": "9876"},
    )

    assert response.status_code == 200
    assert b"Die PINs stimmen nicht \xc3\xbcberein." in response.content
    participant.refresh_from_db()
    assert getattr(participant, "pin", None) is None or not participant.pin.pin_hash
    assert KIOSK_PARTICIPANT_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_kiosk_meal_signup_without_price_rule_shows_error(client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    # intentionally not creating a PriceRule for dinner

    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
def test_kiosk_books_snack_successfully(client):
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
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
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
