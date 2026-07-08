from datetime import date
from decimal import Decimal

import pytest

from billing.forms import CampForm, FirstAdminSetupForm, KioskLoginForm, ParticipantForm, UserCreateForm, UserEditForm
from billing.roles import ROLE_EDITOR
from tests.factories import CampFactory, ParticipantFactory, SuperUserFactory


@pytest.mark.django_db
def test_camp_form_saves_meal_booking_cutoff_time():
    camp = CampFactory()
    form = CampForm(
        instance=camp,
        data={
            "name": camp.name,
            "year": camp.year,
            "starts_on": "",
            "ends_on": "",
            "is_active": "on",
            "meal_booking_cutoff_time": "11:30",
            "shift_ratio_per_night": "0.0",
            "notes": "",
        },
    )

    assert form.is_valid(), form.errors
    saved_camp = form.save()

    assert saved_camp.meal_booking_cutoff_time.hour == 11
    assert saved_camp.meal_booking_cutoff_time.minute == 30


@pytest.mark.django_db
def test_only_one_camp_remains_active():
    first = CampFactory(is_active=True)
    second = CampFactory(name="Winterlager", is_active=True)

    first.refresh_from_db()
    assert first.is_active is False
    assert second.is_active is True


@pytest.mark.django_db
def test_deleting_active_camp_activates_remaining_camp():
    active = CampFactory(is_active=True)
    remaining = CampFactory(name="Winterlager", is_active=False)

    active.delete()

    remaining.refresh_from_db()
    assert remaining.is_active is True


@pytest.mark.django_db
def test_kiosk_login_form_only_lists_non_archived_participants_from_active_camp():
    active_camp = CampFactory(is_active=True)
    visible = ParticipantFactory(camp=active_camp)
    archived = ParticipantFactory(camp=active_camp, archived_at="2026-06-09T12:00:00Z")
    inactive_camp = CampFactory(name="Altes Lager", is_active=False)
    hidden = ParticipantFactory(camp=inactive_camp)

    form = KioskLoginForm()

    assert list(form.fields["participant"].queryset) == [visible]
    assert archived not in form.fields["participant"].queryset
    assert hidden not in form.fields["participant"].queryset


@pytest.mark.django_db
def test_first_admin_setup_form_commit_false():
    form = FirstAdminSetupForm(
        data={
            "username": "admin2",
            "email": "admin2@example.org",
            "password1": "pass-123",
            "password2": "pass-123",
        }
    )
    assert form.is_valid(), form.errors
    user = form.save(commit=False)
    assert not user.pk


@pytest.mark.django_db
def test_user_create_form_commit_false():
    form = UserCreateForm(
        data={
            "username": "editor2",
            "email": "editor2@example.org",
            "role": ROLE_EDITOR,
            "password1": "pass-123",
            "password2": "pass-123",
        }
    )
    assert form.is_valid(), form.errors
    user = form.save(commit=False)
    assert not user.pk


@pytest.mark.django_db
def test_user_edit_form_prevents_superuser_role_change():
    superuser = SuperUserFactory(username="super")
    form = UserEditForm(
        instance=superuser,
        data={
            "email": "super@example.org",
            "is_active": True,
            "role": ROLE_EDITOR,
        },
    )
    assert not form.is_valid()
    assert "Superuser bleiben immer Admins." in form.errors["role"]


@pytest.mark.django_db
def test_participant_form_accepts_arrival_and_departure_dates():
    form = ParticipantForm(
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "",
            "phone": "",
            "status": "registered",
            "hilfssatz": "1.0000",
            "berufssatz": "1.0000",
            "arrival_date": "2026-07-01",
            "departure_date": "2026-07-10",
            "booked_nights": "0",
            "actual_nights": "0",
            "notes": "",
        }
    )

    assert form.is_valid(), form.errors
    participant = form.save(commit=False)
    assert participant.arrival_date.isoformat() == "2026-07-01"
    assert participant.departure_date.isoformat() == "2026-07-10"


@pytest.mark.django_db
def test_participant_form_rejects_departure_before_arrival():
    form = ParticipantForm(
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "",
            "phone": "",
            "status": "registered",
            "hilfssatz": "1.0000",
            "berufssatz": "1.0000",
            "arrival_date": "2026-07-10",
            "departure_date": "2026-07-01",
            "booked_nights": "0",
            "actual_nights": "0",
            "notes": "",
        }
    )

    assert not form.is_valid()
    assert "Die Abreise muss nach der Anreise liegen." in form.errors["departure_date"]


@pytest.mark.django_db
def test_participant_form_renders_date_inputs_with_iso_values():
    participant = ParticipantFactory(arrival_date=date(2026, 7, 1), departure_date=date(2026, 7, 10))

    content = ParticipantForm(instance=participant).as_p()

    assert 'name="arrival_date" value="2026-07-01"' in content
    assert 'name="departure_date" value="2026-07-10"' in content


@pytest.mark.django_db
def test_camp_flat_rate_settings_form_save_without_camp():
    from billing.forms import CampFlatRateSettingsForm

    form = CampFlatRateSettingsForm()
    with pytest.raises(ValueError, match="requires camp"):
        form.save()


@pytest.mark.django_db
def test_camp_flat_rate_settings_form_updates_and_creates_rules():
    from billing.forms import CampFlatRateSettingsForm
    from billing.models import PriceRule
    from tests.factories import CampFactory

    camp = CampFactory()

    # Create one rule so the form updates it, and creates others
    PriceRule.objects.create(
        camp=camp,
        kind=PriceRule.Kind.CAMP_FLAT,
        camp_flat_role=PriceRule.CampFlatRole.PARTICIPANT,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
        unit_price="10.00",
    )

    form = CampFlatRateSettingsForm(
        camp=camp,
        data={
            "participant_1w_price": "15.00",
            "participant_1w_foerdersatz": "40",
            "participant_2w_price": "25.00",
            "participant_2w_foerdersatz": "50",
            "companion_1w_price": "12.00",
            "companion_1w_foerdersatz": "20",
            "companion_2w_price": "22.00",
            "companion_2w_foerdersatz": "0",
        },
    )
    assert form.is_valid(), form.errors
    form.save()
    assert PriceRule.objects.filter(camp=camp).count() == 4
    assert PriceRule.objects.get(
        camp=camp,
        camp_flat_role=PriceRule.CampFlatRole.PARTICIPANT,
        camp_flat_duration=PriceRule.CampFlatDuration.ONE_WEEK,
    ).foerdersatz == Decimal("0.4000")


@pytest.mark.django_db
def test_meal_standard_prices_form_save():
    from billing.forms import MealStandardPricesForm
    from billing.models import PriceRule
    from tests.factories import CampFactory

    camp = CampFactory()

    form = MealStandardPricesForm(
        camp=camp,
        data={
            "breakfast_adult_price": "5.00",
            "breakfast_adult_foerdersatz": "100",
            "breakfast_child_price": "3.00",
            "breakfast_child_foerdersatz": "75",
            "dinner_adult_price": "8.00",
            "dinner_adult_foerdersatz": "40",
            "dinner_child_price": "4.00",
            "dinner_child_foerdersatz": "0",
        },
    )
    assert form.is_valid(), form.errors
    form.save()
    assert PriceRule.objects.filter(camp=camp).count() == 4

    # Now load and save again to trigger the update paths
    form2 = MealStandardPricesForm(
        camp=camp,
        data={
            "breakfast_adult_price": "6.00",
            "breakfast_adult_foerdersatz": "90",
            "breakfast_child_price": "4.00",
            "breakfast_child_foerdersatz": "70",
            "dinner_adult_price": "9.00",
            "dinner_adult_foerdersatz": "30",
            "dinner_child_price": "5.00",
            "dinner_child_foerdersatz": "0",
        },
    )
    assert form2.is_valid()
    form2.save()
    assert PriceRule.objects.filter(camp=camp).count() == 4


def test_subsidy_percent_field_rejects_values_outside_percentage_range():
    from billing.forms import PriceRuleForm
    from billing.models import PriceRule

    form = PriceRuleForm(
        data={
            "kind": PriceRule.Kind.DRINK,
            "name": "Cola",
            "unit_price": "2.50",
            "foerdersatz": "100.01",
            "applies_to_children": "on",
            "applies_to_adults": "on",
            "applies_to_companions": "on",
        }
    )

    assert not form.is_valid()
    assert "foerdersatz" in form.errors
