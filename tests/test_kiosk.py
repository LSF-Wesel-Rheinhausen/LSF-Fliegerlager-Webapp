from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from billing.models import Charge, MealSignup, PriceRule
from billing.views import KIOSK_PARTICIPANT_SESSION_KEY, KIOSK_PIN_SETUP_SESSION_KEY
from tests.factories import CampFactory, ParticipantFactory, PriceRuleFactory, UserFactory


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
    assert b'class="drink-card"' in response.content
    assert b'name="drink-price_rule"' in response.content
    assert b"1x tippen" in response.content
    assert b'data-timeout-ms="120000"' in response.content
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
    PriceRuleFactory(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=MealSignup.Meal.DINNER,
        is_default=True,
        applies_to_children=False,
        applies_to_adults=True,
        name="Abendessen",
        unit_price=Decimal("7.00"),
        foerderfaehig=False,
    )
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    payload = {
        "action": "meal",
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
    assert charge.description == "Abendessen Abendessen"
    assert charge.unit_price == Decimal("7.00")


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
        meal_date=date(2025, 7, 2),
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
            "meal-meal_date": date(2025, 7, 1).isoformat(),
            "meal-meal": MealSignup.Meal.BREAKFAST,
            "meal-variant": MealSignup.Variant.NORMAL_CHILD,
        },
    )

    # Book override day
    client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_date": date(2025, 7, 2).isoformat(),
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
            "meal-meal_date": date(2025, 7, 1).isoformat(),
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
