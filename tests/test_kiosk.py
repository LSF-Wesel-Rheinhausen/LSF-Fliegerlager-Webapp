from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from tests.factories import CampFactory, ParticipantFactory, PriceRuleFactory, UserFactory

from billing.models import Charge, MealSignup, PriceRule
from billing.views import KIOSK_PARTICIPANT_SESSION_KEY, KIOSK_PIN_SETUP_SESSION_KEY


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
def test_kiosk_home_hides_normal_admin_header_and_renders_stepper_controls(client):
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
    assert b"data-kiosk-stepper" in response.content
    assert b"data-stepper-increment" in response.content
    assert b"data-stepper-decrement" in response.content
    assert b'inputmode="numeric"' in response.content
    assert b"2 * 60 * 1000" in response.content
    assert reverse("kiosk-logout").encode() in response.content
    assert "Förderung anwenden".encode() not in response.content


@pytest.mark.django_db
def test_kiosk_pin_setup_uses_inactivity_logout_timer(client):
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    session = client.session
    session[KIOSK_PIN_SETUP_SESSION_KEY] = participant.pk
    session.save()

    response = client.get(reverse("kiosk-pin-setup"))

    assert response.status_code == 200
    assert b"2 * 60 * 1000" in response.content
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
        foerderfaehig=True,
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = client.post(
        reverse("kiosk-home"),
        {
            "action": "drink",
            "drink-price_rule": PriceRule.objects.get(camp=camp, kind=PriceRule.Kind.DRINK).pk,
            "drink-quantity": 2,
        },
    )

    assert response.status_code == 302
    entry = Charge.objects.get(participant=participant, kind=Charge.Kind.DRINK)
    assert entry.description == "Getränk"
    assert entry.quantity == Decimal("2.00")
    assert entry.unit_price == Decimal("2.50")
    assert entry.foerderfaehig is True


@pytest.mark.django_db
def test_kiosk_meal_signup_updates_existing_signup_and_creates_charge(client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    meal_rule = PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        name="Mittagessen",
        unit_price=Decimal("7.00"),
        foerderfaehig=False,
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    payload = {
        "action": "meal",
        "meal-price_rule": meal_rule.pk,
        "meal-meal_date": date(2025, 7, 1).isoformat(),
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
    assert charge.description == "Mittagessen Abendessen"
    assert charge.unit_price == Decimal("7.00")
