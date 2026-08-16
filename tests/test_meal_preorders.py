from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from billing.kiosk_access import KIOSK_PARTICIPANT_SESSION_KEY
from billing.models import MealOrder, MealSignup, PriceRule
from tests.factories import CampFactory, GroupFactory, ParticipantFactory, SuperUserFactory, UserFactory


@pytest.mark.django_db
def test_camp_preorder_switches_are_closed_by_default():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 7))

    assert camp.allow_breakfast_prebooking_before_camp is False
    assert camp.allow_dinner_prebooking_before_camp is False


@pytest.mark.django_db
def test_admin_preorder_settings_show_camp_period_and_save_meals_independently(client):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 7), is_active=True)
    client.force_login(SuperUserFactory())

    response = client.get(reverse("preorder-settings"))

    assert response.status_code == 200
    assert "01.07.2026" in response.content.decode()
    assert "07.07.2026" in response.content.decode()

    response = client.post(
        reverse("preorder-settings"),
        {"allow_breakfast_prebooking_before_camp": "on"},
    )

    assert response.status_code == 302
    camp.refresh_from_db()
    assert camp.allow_breakfast_prebooking_before_camp is True
    assert camp.allow_dinner_prebooking_before_camp is False


@pytest.mark.django_db
def test_preorder_settings_are_admin_only(client):
    user = UserFactory()
    user.groups.add(GroupFactory(name="Bearbeiter"))
    client.force_login(user)

    response = client.get(reverse("preorder-settings"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


@pytest.mark.django_db
def test_admin_navigation_links_to_preorders_and_non_admin_does_not_see_it(client):
    client.force_login(SuperUserFactory())
    admin_content = client.get(reverse("camp-list")).content.decode()
    toolbar = admin_content.split('<div class="toolbar">', 1)[1].split("</div>", 1)[0]

    assert reverse("preorder-settings") in admin_content
    assert toolbar.count("Vorbestellungen") == 1
    assert reverse("preorder-settings") not in client.get(reverse("admin-guide")).content.decode()

    client.force_login(UserFactory())
    non_admin_content = client.get(reverse("camp-list")).content.decode()

    assert reverse("preorder-settings") not in non_admin_content
    assert "Vorbestellungen" not in non_admin_content


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("meal", "flag"),
    [
        (MealSignup.Meal.BREAKFAST, "allow_breakfast_prebooking_before_camp"),
        (MealSignup.Meal.DINNER, "allow_dinner_prebooking_before_camp"),
    ],
)
def test_kiosk_offers_only_admin_released_preorder_action_before_camp(kiosk_client, monkeypatch, meal, flag):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 6, 30))
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 6, 30))
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 3),
        **{flag: True},
    )
    participant = ParticipantFactory(camp=camp)
    for meal_type in (MealSignup.Meal.BREAKFAST, MealSignup.Meal.DINNER):
        PriceRule.objects.create(
            camp=camp,
            kind=PriceRule.Kind.MEAL,
            meal_type=meal_type,
            is_default=True,
            applies_to_adults=True,
            unit_price=Decimal("5.00"),
        )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["preorder_meals"] == {meal}
    assert f'data-preorder-meal="{meal}"' in content
    other_meal = MealSignup.Meal.DINNER if meal == MealSignup.Meal.BREAKFAST else MealSignup.Meal.BREAKFAST
    assert f'data-preorder-meal="{other_meal}"' not in content
    assert {day["date"] for day in response.context["breakfast_calendar_days"]} == {
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
    }


@pytest.mark.django_db
@pytest.mark.parametrize("flag", ["allow_breakfast_prebooking_before_camp", "allow_dinner_prebooking_before_camp"])
def test_pre_camp_kiosk_renders_only_released_preorder_ui(kiosk_client, monkeypatch, flag):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 6, 30))
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 6, 30))
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 3),
        **{flag: True},
    )
    participant = ParticipantFactory(camp=camp)
    for meal_type in (MealSignup.Meal.BREAKFAST, MealSignup.Meal.DINNER):
        PriceRule.objects.create(
            camp=camp,
            kind=PriceRule.Kind.MEAL,
            meal_type=meal_type,
            is_default=True,
            applies_to_adults=True,
            unit_price=Decimal("5.00"),
        )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))
    content = response.content.decode()

    assert "Verpflegung buchen" in content
    assert response.context["is_pre_camp"] is True
    assert response.context["show_meal_area"] is False
    assert "Getränk buchen" not in content
    assert "Dienste" not in content
    assert "Check-in" not in content
    if flag == "allow_breakfast_prebooking_before_camp":
        assert "Frühstück vorbestellen" in content
        assert 'id="meal-calendar-dialog"' not in content
        assert 'id="breakfast-meal-dialog"' in content
    else:
        assert "Abendessen vorbestellen" in content
        assert 'id="breakfast-meal-dialog"' not in content
        assert 'id="meal-calendar-dialog"' in content


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("meal", "flag"),
    [
        (MealSignup.Meal.BREAKFAST, "allow_breakfast_prebooking_before_camp"),
        (MealSignup.Meal.DINNER, "allow_dinner_prebooking_before_camp"),
    ],
)
def test_kiosk_books_each_released_meal_before_camp(kiosk_client, monkeypatch, meal, flag):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 6, 30))
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 6, 30))
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 3),
        **{flag: True},
    )
    participant = ParticipantFactory(camp=camp)
    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=meal,
        is_default=True,
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
            "meal-meal_dates": date(2026, 7, 1).isoformat(),
            "meal-meal": meal,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 302, response.context["meal_form"].errors
    assert MealSignup.objects.filter(participant=participant, meal=meal, meal_date=date(2026, 7, 1)).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("meal", "flag"),
    [
        (MealSignup.Meal.BREAKFAST, "allow_breakfast_prebooking_before_camp"),
        (MealSignup.Meal.DINNER, "allow_dinner_prebooking_before_camp"),
    ],
)
def test_kiosk_keeps_sent_preorder_day_locked(kiosk_client, monkeypatch, meal, flag):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 6, 30))
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 6, 30))
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 3),
        **{flag: True},
    )
    participant = ParticipantFactory(camp=camp)
    sent_date = date(2026, 7, 2)
    MealOrder.objects.create(camp=camp, meal_date=sent_date)
    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=meal,
        is_default=True,
        applies_to_adults=True,
        unit_price=Decimal("5.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))
    calendar_key = "breakfast_calendar_days" if meal == MealSignup.Meal.BREAKFAST else "meal_calendar_days"
    calendar = response.context[calendar_key]
    sent_slot = next(day for day in calendar if day["date"] == sent_date)

    if meal == MealSignup.Meal.BREAKFAST:
        assert sent_slot["locked"] is False
        assert sent_slot["booking_state"] == "open"
    else:
        assert sent_slot["locked"] is True
        assert sent_slot["lock_message"] == "Die Bestellung für 02.07.2026 wurde bereits abgeschickt."

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "meal",
            "meal-meal_dates": sent_date.isoformat(),
            "meal-meal": meal,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    if meal == MealSignup.Meal.BREAKFAST:
        assert response.status_code == 302
        assert MealSignup.objects.filter(participant=participant, meal=meal, meal_date=sent_date).exists()
    else:
        assert response.status_code == 200
        assert (
            "Die Bestellung für 02.07.2026 wurde bereits abgeschickt." in response.context["meal_form"].errors.as_text()
        )
        assert not MealSignup.objects.filter(participant=participant, meal=meal, meal_date=sent_date).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("meal", [MealSignup.Meal.BREAKFAST, MealSignup.Meal.DINNER])
@pytest.mark.parametrize("meal_date", [date(2026, 6, 30), date(2026, 7, 4)])
def test_kiosk_rejects_meal_booking_outside_camp_before_camp(kiosk_client, monkeypatch, meal, meal_date):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 6, 30))
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 6, 30))
    preorder_flag = (
        "allow_breakfast_prebooking_before_camp"
        if meal == MealSignup.Meal.BREAKFAST
        else "allow_dinner_prebooking_before_camp"
    )
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 3),
        **{preorder_flag: True},
    )
    participant = ParticipantFactory(camp=camp)
    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=meal,
        is_default=True,
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
            "meal-meal": meal,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 200
    assert "meal_dates" in response.context["meal_form"].errors
    assert not MealSignup.objects.filter(participant=participant).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("meal", [MealSignup.Meal.BREAKFAST, MealSignup.Meal.DINNER])
def test_kiosk_rejects_unreleased_meal_post_before_camp(kiosk_client, monkeypatch, meal):
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: date(2026, 6, 30))
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 6, 30))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 3))
    participant = ParticipantFactory(camp=camp)
    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.MEAL,
        meal_type=meal,
        is_default=True,
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
            "meal-meal_dates": date(2026, 7, 1).isoformat(),
            "meal-meal": meal,
            "meal-variant": MealSignup.Variant.NORMAL,
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("kiosk-home")
    assert not MealSignup.objects.filter(participant=participant, meal=meal).exists()
