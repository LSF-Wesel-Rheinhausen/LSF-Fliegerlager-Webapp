from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib import admin
from django.db import connection
from django.db.models import QuerySet
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from billing.models import (
    Camp,
    Charge,
    MealBookingOverride,
    MealOrder,
    MealPlanEntry,
    MealSignup,
    ParticipantFamilyMember,
)
from billing.permissions import HUEBERS_GROUP
from billing.services import calculate_meal_overview
from tests.factories import CampFactory, GroupFactory, ParticipantFactory, SuperUserFactory, UserFactory


def test_meal_order_is_read_only_in_raw_django_admin():
    model_admin = admin.site._registry[MealOrder]

    assert model_admin.has_add_permission(None) is False
    assert model_admin.has_change_permission(None) is False
    assert model_admin.has_delete_permission(None) is False


@pytest.mark.django_db
def test_calculate_meal_overview_counts_active_variants_and_retractions():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 1))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    child = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Kind",
        last_name="A",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    linked_participant = ParticipantFactory(camp=camp, first_name="Grace", last_name="B")
    deleted_charge = Charge.objects.create(
        participant=linked_participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=1,
        unit_price=Decimal("7.00"),
        occurred_on=date(2026, 7, 1),
    )
    MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.BREAKFAST,
        variant=MealSignup.Variant.NORMAL,
    )
    MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )
    MealSignup.objects.create(
        participant=participant,
        family_member=child,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.VEGAN_CHILD,
    )
    MealSignup.objects.create(
        participant=linked_participant,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.VEGAN,
        status=MealSignup.Status.RETRACTED,
        charge=deleted_charge,
    )

    overview = calculate_meal_overview(camp)

    assert len(overview[0].meals) == 1
    dinner = overview[0].meals[0]
    assert dinner.meal == MealSignup.Meal.DINNER
    assert dinner.variant_counts["Mit Fleisch"] == 1
    assert dinner.variant_counts["Vegan Kind"] == 1
    assert dinner.active_total == 2
    assert dinner.retracted_total == 1


@pytest.mark.django_db
def test_calculate_meal_overview_separates_breakfast_details_and_family_targets():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 2))
    first_guardian = ParticipantFactory(camp=camp, first_name="Alex", last_name="Konto")
    second_guardian = ParticipantFactory(camp=camp, first_name="Bea", last_name="Konto")
    first_child = ParticipantFamilyMember.objects.create(
        guardian=first_guardian,
        first_name="Sam",
        last_name="Muster",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    second_child = ParticipantFamilyMember.objects.create(
        guardian=second_guardian,
        first_name="Sam",
        last_name="Muster",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    MealSignup.objects.create(
        participant=first_guardian,
        family_member=first_child,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.BREAKFAST,
        variant=MealSignup.Variant.NORMAL_CHILD,
    )
    MealSignup.objects.create(
        participant=second_guardian,
        family_member=second_child,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.BREAKFAST,
        variant=MealSignup.Variant.VEGAN_CHILD,
        status=MealSignup.Status.RETRACTED,
    )
    MealSignup.objects.create(
        participant=first_guardian,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )

    overview = calculate_meal_overview(camp)

    assert [day.meal_date for day in overview] == [date(2026, 7, 1), date(2026, 7, 2)]
    breakfast = overview[0].breakfast
    assert breakfast.active_total == 1
    assert breakfast.retracted_total == 1
    assert breakfast.variant_counts == {
        "Mit Fleisch": 0,
        "Vegan": 0,
        "Mit Fleisch Kind": 1,
        "Vegan Kind": 0,
    }
    assert [(booking.target_name, booking.payment_account_name) for booking in breakfast.bookings] == [
        ("Sam Muster", "Alex Konto"),
        ("Sam Muster", "Bea Konto"),
    ]
    assert [booking.status_label for booking in breakfast.bookings] == ["Gebucht", "Zurückgenommen"]
    assert breakfast.booking_total == 2
    assert overview[0].dinner.active_total == 1
    assert overview[1].breakfast.active_total == 0


@pytest.mark.django_db
def test_calculate_meal_overview_preserves_companion_target_and_guardian_account():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 1))
    guardian = ParticipantFactory(camp=camp, first_name="Guardian", last_name="Account")
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Companion",
        last_name="Identity",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    MealSignup.objects.create(
        participant=guardian,
        family_member=companion,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )

    booking = calculate_meal_overview(camp)[0].dinner.bookings[0]

    assert booking.target_name == "Companion Identity"
    assert booking.payment_account_name == "Guardian Account"


@pytest.mark.django_db
def test_calculate_meal_overview_uses_bounded_queries_and_ignores_out_of_camp_signups():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 1))
    participant = ParticipantFactory(camp=camp)
    MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 6, 30),
        meal=MealSignup.Meal.BREAKFAST,
        variant=MealSignup.Variant.NORMAL,
    )

    with CaptureQueriesContext(connection) as queries:
        overview = calculate_meal_overview(camp)

    assert len(queries) <= 2
    signup_query = next(query["sql"] for query in queries if "billing_mealsignup" in query["sql"])
    assert '"meal_date" BETWEEN' in signup_query
    assert len(overview) == 1
    assert overview[0].breakfast.active_total == 0


@pytest.mark.django_db
def test_camp_meal_overview_renders_counts_for_admin(client):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 1))
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="A")
    MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )
    client.force_login(SuperUserFactory())

    response = client.get(reverse("camp-meal-overview", args=[camp.pk]))

    assert response.status_code == 200
    assert b"Essens\xc3\xbcbersicht" in response.content
    assert b"N\xc3\xa4chster Tag" in response.content
    assert b"Abendessen" in response.content
    assert b"Fr\xc3\xbchst\xc3\xbcck" in response.content
    assert b"Fr\xc3\xbchst\xc3\xbccksvorbestellungen" in response.content
    assert b'data-meal-section="dinner"' in response.content
    assert b'data-meal-section="breakfast"' in response.content
    assert b"<strong>1</strong>" in response.content


@pytest.mark.django_db
def test_camp_meal_overview_exposes_dinner_calendar_states_without_breakfast_locks(client, monkeypatch):
    today = date(2026, 7, 1)
    fixed_now = timezone.make_aware(datetime(2026, 7, 1, 10, 0))
    monkeypatch.setattr("billing.services.timezone.localdate", lambda: today)
    monkeypatch.setattr("billing.services.timezone.localtime", lambda value=None, timezone=None: fixed_now)
    camp = CampFactory(starts_on=today - timedelta(days=1), ends_on=date(2026, 7, 2))
    client.force_login(SuperUserFactory())

    content = client.get(reverse("camp-meal-overview", args=[camp.pk])).content.decode()

    calendar = content.split('data-meal-calendar="dinner"', 1)[1].split('data-meal-section="dinner"', 1)[0]
    breakfast = content.split('data-meal-section="breakfast"', 1)[1]
    assert "Vergangen" in calendar
    assert "Offen" in calendar
    assert not any(label in breakfast for label in ("Sperren", "Entsperren"))


@pytest.mark.django_db
def test_camp_meal_overview_preloads_manual_dinner_states_for_all_days(client):
    today = timezone.localdate()
    camp = CampFactory(starts_on=today, ends_on=today + timedelta(days=6))
    user = SuperUserFactory()
    MealBookingOverride.objects.create(
        camp=camp,
        meal_date=today + timedelta(days=1),
        meal=MealSignup.Meal.DINNER,
        state=MealBookingOverride.State.CLOSED,
        changed_by=user,
    )
    client.force_login(user)

    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("camp-meal-overview", args=[camp.pk]))

    override_queries = [query for query in queries if "billing_mealbookingoverride" in query["sql"]]
    sent_order_queries = [
        query for query in queries if "billing_mealorder" in query["sql"] and '"meal_date" IN' in query["sql"]
    ]
    assert response.status_code == 200
    assert len(override_queries) == 1
    assert len(sent_order_queries) == 1


@pytest.mark.django_db
def test_camp_meal_overview_renders_sent_order_as_locked_without_manual_override_action(client):
    today = timezone.localdate()
    meal_date = today + timedelta(days=1)
    camp = CampFactory(starts_on=today, ends_on=meal_date)
    MealOrder.objects.create(camp=camp, meal_date=meal_date, is_sent=True)
    client.force_login(SuperUserFactory())

    response = client.get(reverse("camp-meal-overview", args=[camp.pk]))

    calendar = (
        response.content.decode().split('data-meal-calendar="dinner"', 1)[1].split('data-meal-section="dinner"', 1)[0]
    )
    sent_card = calendar.split(f'datetime="{meal_date.isoformat()}"', 1)[1].split("</article>", 1)[0]
    assert "Bestellung versandt" in sent_card
    assert 'name="state" value="not_sent"' in sent_card
    assert 'name="state" value="open"' not in sent_card
    assert 'name="state" value="closed"' not in sent_card


@pytest.mark.django_db
def test_camp_meal_overview_renders_booking_details_only_in_their_meal_dialogs(client):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 1))
    guardian = ParticipantFactory(camp=camp, first_name="Alex", last_name="Konto")
    child = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Sam",
        last_name="Muster",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    dinner_guest = ParticipantFactory(camp=camp, first_name="Dora", last_name="Dinner")
    MealSignup.objects.create(
        participant=guardian,
        family_member=child,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.BREAKFAST,
        variant=MealSignup.Variant.VEGAN_CHILD,
        status=MealSignup.Status.RETRACTED,
    )
    MealSignup.objects.create(
        participant=dinner_guest,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )
    client.force_login(SuperUserFactory())

    response = client.get(reverse("camp-meal-overview", args=[camp.pk]))

    content = response.content.decode()
    breakfast_dialog = content.split('id="breakfast-detail-20260701"', 1)[1].split("</dialog>", 1)[0]
    dinner_dialog = content.split('id="dinner-detail-20260701"', 1)[1].split("</dialog>", 1)[0]
    assert all(value in breakfast_dialog for value in ["Sam Muster", "Alex Konto", "Vegan Kind", "Zurückgenommen"])
    assert "Dora Dinner" not in breakfast_dialog
    assert all(value in dinner_dialog for value in ["Dora Dinner", "Mit Fleisch", "Gebucht"])
    assert "Sam Muster" not in dinner_dialog


@pytest.mark.django_db
def test_camp_meal_overview_escapes_booking_names(client):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 1))
    participant = ParticipantFactory(camp=camp, first_name="<script>alert(1)</script>", last_name="Guest")
    MealSignup.objects.create(
        participant=participant,
        meal_date=date(2026, 7, 1),
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
    )
    client.force_login(SuperUserFactory())

    content = client.get(reverse("camp-meal-overview", args=[camp.pk])).content.decode()

    assert "&lt;script&gt;alert(1)&lt;/script&gt; Guest" in content
    assert "<script>alert(1)</script> Guest" not in content


@pytest.mark.django_db
def test_camp_meal_overview_renders_and_saves_menu_for_huebers(client):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 2))
    huebers = UserFactory()
    huebers.groups.add(GroupFactory(name=HUEBERS_GROUP))
    client.force_login(huebers)

    response = client.get(reverse("camp-meal-overview", args=[camp.pk]))

    assert response.status_code == 200
    assert b"Speiseplan speichern" in response.content
    assert b"meal_plan-description_20260701" in response.content
    assert reverse("information-email-compose", args=[camp.pk]).encode() in response.content

    response = client.post(
        reverse("camp-meal-overview", args=[camp.pk]),
        {
            "action": "meal_plan",
            "meal_plan-description_20260701": "Pasta mit Salat",
            "meal_plan-description_20260702": "",
        },
    )

    assert response.status_code == 302
    entry = MealPlanEntry.objects.get(camp=camp, meal_date=date(2026, 7, 1), meal=MealSignup.Meal.DINNER)
    assert entry.description == "Pasta mit Salat"


@pytest.mark.django_db
def test_meal_overview_marks_next_day_order_as_sent(client):
    camp = CampFactory()
    user = SuperUserFactory()
    client.force_login(user)

    response = client.post(reverse("meal-order-mark-sent", args=[camp.pk]))

    assert response.status_code == 302
    order = MealOrder.objects.get(camp=camp)
    assert order.ordered_by == user


@pytest.mark.django_db
def test_meal_overview_can_unmark_sent_order_for_current_camp_day(client, monkeypatch):
    today = timezone.localdate()
    monkeypatch.setattr("billing.views.timezone.localdate", lambda: today)
    camp = CampFactory(starts_on=today, ends_on=today + timedelta(days=1))
    order = MealOrder.objects.create(camp=camp, meal_date=today, is_sent=True)
    client.force_login(SuperUserFactory())

    response = client.post(
        reverse("meal-order-mark-sent", args=[camp.pk]),
        {"state": "not_sent", "meal_date": today.isoformat()},
    )

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.is_sent is False
    assert not MealOrder.objects.filter(camp=camp, meal_date=today + timedelta(days=1)).exists()


@pytest.mark.django_db
def test_meal_overview_not_sent_does_not_create_missing_order(client):
    camp = CampFactory()
    client.force_login(SuperUserFactory())

    response = client.post(reverse("meal-order-mark-sent", args=[camp.pk]), {"state": "not_sent"})

    assert response.status_code == 302
    assert not MealOrder.objects.filter(camp=camp).exists()


@pytest.mark.django_db
def test_meal_overview_not_sent_does_not_rewrite_already_unmarked_order(client):
    today = timezone.localdate()
    camp = CampFactory(starts_on=today, ends_on=today + timedelta(days=1))
    original_user = UserFactory()
    original_unmarked_at = timezone.now() - timedelta(hours=1)
    order = MealOrder.objects.create(
        camp=camp,
        meal_date=today,
        is_sent=False,
        unmarked_at=original_unmarked_at,
        unmarked_by=original_user,
    )
    client.force_login(SuperUserFactory())

    response = client.post(
        reverse("meal-order-mark-sent", args=[camp.pk]),
        {"state": "not_sent", "meal_date": today.isoformat()},
    )

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.unmarked_at == original_unmarked_at
    assert order.unmarked_by == original_user


@pytest.mark.django_db
def test_meal_overview_rejects_unknown_order_state(client):
    camp = CampFactory()
    client.force_login(SuperUserFactory())

    response = client.post(reverse("meal-order-mark-sent", args=[camp.pk]), {"state": "unknown"})

    assert response.status_code == 302
    assert not MealOrder.objects.filter(camp=camp).exists()


@pytest.mark.django_db
def test_meal_overview_rejects_empty_explicit_order_date(client):
    camp = CampFactory()
    order = MealOrder.objects.create(camp=camp, meal_date=timezone.localdate() + timedelta(days=1), is_sent=True)
    client.force_login(SuperUserFactory())

    response = client.post(
        reverse("meal-order-mark-sent", args=[camp.pk]),
        {"state": "not_sent", "meal_date": ""},
    )

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.is_sent is True


@pytest.mark.django_db
def test_marking_order_sent_locks_camp_before_order_row(client, monkeypatch):
    camp = CampFactory()
    user = SuperUserFactory()
    client.force_login(user)
    original_fetch_all = QuerySet._fetch_all
    locked_models = []

    def capture_select_for_update(queryset):
        if queryset._result_cache is None and queryset.query.select_for_update:
            locked_models.append(queryset.model)
        original_fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", capture_select_for_update)

    response = client.post(reverse("meal-order-mark-sent", args=[camp.pk]))

    assert response.status_code == 302
    assert locked_models.index(Camp) < locked_models.index(MealOrder)
