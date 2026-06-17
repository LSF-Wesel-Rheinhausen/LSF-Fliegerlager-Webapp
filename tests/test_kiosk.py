from datetime import date, datetime, time
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from billing.models import (
    Charge,
    Expense,
    MealOrder,
    MealSignup,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    Payment,
    PriceRule,
    UserProfile,
)
from billing.views import KIOSK_PARTICIPANT_SESSION_KEY, KIOSK_PIN_SETUP_SESSION_KEY
from tests.factories import CampFactory, ExpenseFactory, ParticipantFactory, PriceRuleFactory, UserFactory


@pytest.mark.django_db
def test_kiosk_login_redirects_to_pin_setup_when_pin_is_missing(client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")

    response = client.post(reverse("kiosk-login"), {"participant": participant.pk, "pin": "1234"})

    assert response.status_code == 302
    assert response["Location"] == reverse("kiosk-pin-setup")
    assert client.session[KIOSK_PIN_SETUP_SESSION_KEY] == participant.pk
    assert KIOSK_PARTICIPANT_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_kiosk_pin_setup_sets_pin_and_logs_participant_in(client):
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


@pytest.mark.django_db
def test_kiosk_login_rejects_invalid_pin_for_existing_pin(client):
    participant = ParticipantFactory(first_name="Grace", last_name="Hopper")
    participant.pin.set_pin("1234")
    participant.pin.save()

    response = client.post(reverse("kiosk-login"), {"participant": participant.pk, "pin": "9999"})

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
        client.post(reverse("kiosk-login"), {"participant": participant.pk, "pin": "9999"})

    participant.pin.refresh_from_db()
    response = client.post(reverse("kiosk-login"), {"participant": participant.pk, "pin": "1234"})

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
    assert b"Menge w\xc3\xa4hlen" in response.content
    assert b'id="quick-dialog"' in response.content
    assert b'data-timeout-ms="120000"' in response.content
    assert reverse("kiosk-logout").encode() in response.content
    assert "Förderung anwenden".encode() not in response.content
    assert b"Abrechnung ansehen" not in response.content
    assert "Details öffnen".encode() in response.content
    assert b"Brutto:" not in response.content
    assert b"Soll:" not in response.content


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
    assert b"melde dich bitte bei der Lagerleitung" in response.content
    content = response.content.decode()
    meal_section_start = content.index("Essen anmelden")
    status_start = content.index("Die Buchung ist geschlossen.")
    calendar_start = content.index('<div class="meal-calendar"')
    assert meal_section_start < status_start < calendar_start


@pytest.mark.django_db
def test_kiosk_pin_setup_uses_inactivity_logout_timer(client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PIN_SETUP_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-pin-setup"))

    assert response.status_code == 200
    assert b'data-timeout-ms="120000"' in response.content
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


@pytest.mark.django_db
def test_kiosk_meal_signup_updates_existing_signup_and_creates_charge(client):
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
        "meal-meal_date": date(2026, 7, 1).isoformat(),
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
            "meal-meal_date": date(2026, 7, 2).isoformat(),
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
            "meal-meal_date": date(2026, 7, 2).isoformat(),
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
            "meal-meal_date": date(2026, 7, 1).isoformat(),
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
            "meal-meal_date": date(2026, 7, 2).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert b"Buchungen und R\xc3\xbccknahmen" in response.content
    assert not MealSignup.objects.filter(participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_retracts_meal_signup_and_soft_deletes_food_charge(client):
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
            "meal-meal_date": date(2026, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.DINNER,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert "Bitte mindestens eine Person auswählen.".encode() in response.content
    assert not MealSignup.objects.filter(participant=participant).exists()
    assert not Charge.objects.filter(participant=participant, kind=Charge.Kind.FOOD).exists()


@pytest.mark.django_db
def test_kiosk_creates_family_member_and_books_meal_on_guardian(client):
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
            "meal-meal_date": date(2026, 7, 1).isoformat(),
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
def test_kiosk_books_meal_for_linked_participant_on_linked_account(client):
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
            "meal-meal_date": date(2026, 7, 1).isoformat(),
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
def test_kiosk_meal_signup_child_breakfast_override(client):
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
            "meal-meal_date": date(2026, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.BREAKFAST,
            "meal-variant": MealSignup.Variant.NORMAL_CHILD,
        },
    )

    # Book override day
    client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_date": date(2026, 7, 2).isoformat(),
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
            "meal-meal_date": date(2026, 7, 1).isoformat(),
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
