import pytest

from billing.forms import CampForm, FirstAdminSetupForm, UserCreateForm, UserEditForm
from billing.roles import ROLE_EDITOR
from tests.factories import CampFactory, SuperUserFactory


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
            "foerdersatz": "0.5000",
            "notes": "",
        },
    )

    assert form.is_valid(), form.errors
    saved_camp = form.save()

    assert saved_camp.meal_booking_cutoff_time.hour == 11
    assert saved_camp.meal_booking_cutoff_time.minute == 30


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
            "participant_1w_foerderfaehig": True,
            "participant_2w_price": "25.00",
            "participant_2w_foerderfaehig": True,
            "companion_1w_price": "12.00",
            "companion_1w_foerderfaehig": False,
            "companion_2w_price": "22.00",
            "companion_2w_foerderfaehig": False,
        },
    )
    assert form.is_valid(), form.errors
    form.save()
    assert PriceRule.objects.filter(camp=camp).count() == 4


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
            "breakfast_adult_foerderfaehig": True,
            "breakfast_child_price": "3.00",
            "breakfast_child_foerderfaehig": True,
            "dinner_adult_price": "8.00",
            "dinner_adult_foerderfaehig": False,
            "dinner_child_price": "4.00",
            "dinner_child_foerderfaehig": False,
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
            "breakfast_adult_foerderfaehig": True,
            "breakfast_child_price": "4.00",
            "breakfast_child_foerderfaehig": True,
            "dinner_adult_price": "9.00",
            "dinner_adult_foerderfaehig": False,
            "dinner_child_price": "5.00",
            "dinner_child_foerderfaehig": False,
        },
    )
    assert form2.is_valid()
    form2.save()
    assert PriceRule.objects.filter(camp=camp).count() == 4
