from datetime import date, time
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from billing.forms import (
    CampForm,
    ExpenseForm,
    FirstAdminSetupForm,
    KioskLoginForm,
    ParticipantForm,
    ParticipantRegistrationApprovalForm,
    SharedExpenseRequestForm,
    UserCreateForm,
    UserEditForm,
    validate_receipt_upload,
)
from billing.models import Participant, ParticipantFamilyMember
from billing.roles import ROLE_EDITOR
from tests.factories import CampFactory, ParticipantFactory, SuperUserFactory

RECEIPT_ACCEPT = "application/pdf,image/jpeg,image/png,image/heic,.pdf,.jpg,.jpeg,.png,.heic"


@pytest.mark.parametrize("form_class", [ExpenseForm, SharedExpenseRequestForm])
def test_receipt_widgets_allow_file_selection_without_forced_capture(form_class):
    widget = form_class().fields["receipt"].widget

    assert widget.attrs["accept"] == RECEIPT_ACCEPT
    assert "capture" not in widget.attrs


@pytest.mark.parametrize(
    ("form_class", "filename", "content_type", "content"),
    [
        (ExpenseForm, "rechnung.pdf", "application/pdf", b"%PDF-1.7\n"),
        (SharedExpenseRequestForm, "rechnung.jpg", "image/jpeg", b"\xff\xd8\xff\xe0"),
    ],
)
def test_receipt_form_fields_accept_supported_pdf_and_image_uploads(form_class, filename, content_type, content):
    upload = SimpleUploadedFile(filename, content, content_type=content_type)
    form = form_class()
    form.cleaned_data = {"receipt": upload}

    assert form.clean_receipt() is upload


@pytest.mark.parametrize("form_class", [ExpenseForm, SharedExpenseRequestForm])
def test_receipt_form_fields_reject_spoofed_uploads(form_class):
    upload = SimpleUploadedFile("rechnung.pdf", b"not a pdf", content_type="application/pdf")
    form = form_class()
    form.cleaned_data = {"receipt": upload}

    with pytest.raises(ValidationError, match="Dateiinhalt passt nicht zum Dateityp"):
        form.clean_receipt()


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("rechnung.pdf", "application/pdf", b"%PDF-1.7\n"),
        ("rechnung.pdf", None, b"%PDF-1.7\n"),
        ("rechnung.jpg", "image/jpeg", b"\xff\xd8\xff\xe0"),
        ("rechnung.jpeg", "image/jpeg", b"\xff\xd8\xff\xe1"),
        ("rechnung.png", "image/png", b"\x89PNG\r\n\x1a\n"),
        ("rechnung.heic", "image/heic", b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"),
        ("rechnung.heic", "image/heif", b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00heicmif1"),
        ("rechnung.heic", "image/heic", b"\x00\x00\x00\x50ftypheic\x00\x00\x00\x00" + b"mif1" * 16),
    ],
)
def test_validate_receipt_upload_accepts_matching_file_signatures(filename, content_type, content):
    upload = SimpleUploadedFile(filename, content, content_type=content_type)

    assert validate_receipt_upload(upload) is upload


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("rechnung.pdf", "application/pdf", b"<script>alert(1)</script>"),
        ("rechnung.jpg", "image/jpeg", b"not a jpeg"),
        ("rechnung.png", "image/png", b""),
        ("rechnung.heic", "image/heic", b"\x00\x00\x00\x08ftyp"),
        ("rechnung.heic", "image/heic", b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00"),
        ("rechnung.heic", "image/heic", b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00mif1avif"),
    ],
)
def test_validate_receipt_upload_rejects_spoofed_file_contents(filename, content_type, content):
    upload = SimpleUploadedFile(filename, content, content_type=content_type)

    with pytest.raises(ValidationError, match="Dateiinhalt passt nicht zum Dateityp"):
        validate_receipt_upload(upload)


def test_validate_receipt_upload_rejects_mime_type_mismatching_extension():
    upload = SimpleUploadedFile("rechnung.pdf", b"%PDF-1.7\n", content_type="image/png")

    with pytest.raises(ValidationError, match="Dateityp des Rechnungsbelegs wird nicht unterstützt"):
        validate_receipt_upload(upload)


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
    assert saved_camp.meal_booking_cutoff_time == time(11, 30)


@pytest.mark.django_db
def test_camp_form_renders_dates_in_native_format():
    camp = CampFactory(starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 15))
    form = CampForm(instance=camp)
    html = str(form["starts_on"])
    assert 'value="2026-08-01"' in html
    assert 'type="date"' in html


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
    choices = dict(form.fields["participant"].choices)

    assert choices == {"": "Bitte Teilnehmer auswählen", f"participant-{visible.pk}": visible.full_name}
    assert f"participant-{archived.pk}" not in choices
    assert f"participant-{hidden.pk}" not in choices


@pytest.mark.django_db
def test_kiosk_login_form_starts_empty_and_sorts_targets_by_last_name():
    camp = CampFactory(is_active=True)
    lovelace = ParticipantFactory(camp=camp, first_name="Ada", last_name="lovelace")
    adler = ParticipantFactory(camp=camp, first_name="Berta", last_name="Adler")
    hopper = ParticipantFamilyMember.objects.create(
        guardian=lovelace,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )

    form = KioskLoginForm()

    assert list(form.fields["participant"].choices) == [
        ("", "Bitte Teilnehmer auswählen"),
        (f"participant-{adler.pk}", "Berta Adler"),
        (f"family-{hopper.pk}", "Grace Hopper"),
        (f"participant-{lovelace.pk}", "Ada lovelace"),
    ]
    assert 'value="" selected>Bitte Teilnehmer auswählen</option>' in form.as_p()


@pytest.mark.django_db
def test_kiosk_login_form_lists_companions_but_not_children():
    active_camp = CampFactory(is_active=True)
    guardian = ParticipantFactory(camp=active_camp, first_name="Ada", last_name="Lovelace")
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Grace",
        last_name="Hopper",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    child = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Kind",
        last_name="Lovelace",
        role=ParticipantFamilyMember.Role.CHILD,
    )

    form = KioskLoginForm()
    choices = dict(form.fields["participant"].choices)

    assert choices[f"family-{companion.pk}"] == "Grace Hopper"
    assert f"family-{child.pk}" not in choices


@pytest.mark.django_db
def test_kiosk_login_form_keeps_active_companion_choice_unique():
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)
    active_companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Active",
        last_name="Companion",
        role=ParticipantFamilyMember.Role.COMPANION,
        is_active=True,
    )
    inactive_companion = ParticipantFamilyMember.objects.create(
        guardian=participant,
        first_name="Inactive",
        last_name="Companion",
        role=ParticipantFamilyMember.Role.COMPANION,
        is_active=False,
    )

    form = KioskLoginForm()
    values = [str(value) for value, _label in form.fields["participant"].choices]

    assert values.count(f"family-{active_companion.pk}") == 1
    assert f"family-{inactive_companion.pk}" not in values


@pytest.mark.django_db
def test_kiosk_login_companion_label_is_own_name_without_guardian_hint():
    camp = CampFactory(is_active=True)
    guardian = ParticipantFactory(camp=camp, first_name="Guardian", last_name="Account")
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Own",
        last_name="Identity",
        role=ParticipantFamilyMember.Role.COMPANION,
    )

    form = KioskLoginForm()

    label = dict(form.fields["participant"].choices)[f"family-{companion.pk}"]
    assert label == companion.full_name
    assert "Begleitung von" not in label


@pytest.mark.django_db
def test_kiosk_login_duplicate_companion_names_use_neutral_deterministic_suffixes():
    camp = CampFactory(is_active=True)
    guardians = [ParticipantFactory(camp=camp, first_name=f"Guardian {index}") for index in (1, 2)]
    companions = [
        ParticipantFamilyMember.objects.create(
            guardian=guardian,
            first_name="Same",
            last_name="Name",
            role=ParticipantFamilyMember.Role.COMPANION,
        )
        for guardian in guardians
    ]

    form = KioskLoginForm()
    labels = [dict(form.fields["participant"].choices)[f"family-{companion.pk}"] for companion in companions]

    assert labels == ["Same Name", "Same Name (2)"]
    assert all("Begleitung von" not in label for label in labels)


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


def test_participant_subsidy_rates_default_to_zero():
    participant = Participant()

    assert participant.hilfssatz == Decimal("0.0000")
    assert participant.berufssatz == Decimal("0.0000")


@pytest.mark.django_db
def test_registration_approval_requires_both_rates_for_youth_group():
    participant = ParticipantFactory(is_youth_group=True)
    form = ParticipantRegistrationApprovalForm(
        data={
            "is_youth_group": "on",
            "price_attributes_confirmed": "on",
        },
        instance=participant,
    )

    assert not form.is_valid()
    assert form.errors["hilfssatz"] == ["Bitte gib den Hilfssatz für die Jugendgruppe ein."]
    assert form.errors["berufssatz"] == ["Bitte gib den Berufssatz für die Jugendgruppe ein."]


@pytest.mark.django_db
def test_registration_approval_accepts_zero_and_fractional_youth_group_rates():
    participant = ParticipantFactory(is_youth_group=True)
    form = ParticipantRegistrationApprovalForm(
        data={
            "is_youth_group": "on",
            "hilfssatz": "0",
            "berufssatz": "0.3300",
            "price_attributes_confirmed": "on",
        },
        instance=participant,
    )

    assert form.is_valid(), form.errors
    approved_participant = form.save()
    assert approved_participant.hilfssatz == Decimal("0")
    assert approved_participant.berufssatz == Decimal("0.3300")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [("hilfssatz", "-0.0001"), ("berufssatz", "1.0001")],
)
def test_registration_approval_rejects_youth_group_rates_outside_unit_interval(field_name, invalid_value):
    participant = ParticipantFactory(is_youth_group=True)
    data = {
        "is_youth_group": "on",
        "hilfssatz": "0.5000",
        "berufssatz": "0.3300",
        "price_attributes_confirmed": "on",
    }
    data[field_name] = invalid_value
    form = ParticipantRegistrationApprovalForm(data=data, instance=participant)

    assert not form.is_valid()
    assert field_name in form.errors


@pytest.mark.django_db
def test_registration_approval_preserves_rates_when_non_youth_group_fields_are_omitted():
    participant = ParticipantFactory(
        is_youth_group=False,
        hilfssatz=Decimal("0.5000"),
        berufssatz=Decimal("0.3300"),
    )
    form = ParticipantRegistrationApprovalForm(
        data={"price_attributes_confirmed": "on"},
        instance=participant,
    )

    assert form.is_valid(), form.errors
    approved_participant = form.save()
    assert approved_participant.hilfssatz == Decimal("0.5000")
    assert approved_participant.berufssatz == Decimal("0.3300")


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
def test_participant_form_renders_date_inputs_with_native_format():
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
