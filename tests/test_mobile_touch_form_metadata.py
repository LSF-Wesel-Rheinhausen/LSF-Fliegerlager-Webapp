from pathlib import Path

import pytest

from billing.forms import (
    EmailOrUsernameAuthenticationForm,
    ExpenseForm,
    KioskLoginForm,
    KioskSelfEnrollmentForm,
    MealBookingForm,
    ParticipantFamilyMemberForm,
    ParticipantForm,
    PaymentForm,
    QuickBookingForm,
)

CSS = Path(__file__).parents[1] / "src" / "static" / "billing" / "app-v8.css"
TEMPLATES = Path(__file__).parents[1] / "src" / "templates" / "billing"


def test_mobile_touch_targets_cover_stacked_email_recipient_widgets():
    css = CSS.read_text(encoding="utf-8")

    assert '.email-recipient-form input[type="checkbox"]' in css
    assert '.email-recipient-form input[type="radio"]' in css
    assert '.email-recipient-form label:has(> input:is([type="checkbox"], [type="radio"]))' in css
    assert ".form-grid .checkbox-form-field > legend" in css


def test_mobile_touch_target_class_covers_standalone_admin_checkboxes():
    css = CSS.read_text(encoding="utf-8")

    assert ".mobile-touch-target" in css
    assert 'id="select-all-shifts" class="mobile-touch-target"' in (TEMPLATES / "shift_manage.html").read_text(
        encoding="utf-8"
    )
    assert 'class="shift-checkbox mobile-touch-target"' in (TEMPLATES / "shift_manage.html").read_text(encoding="utf-8")
    participant_detail = (TEMPLATES / "participant_detail.html").read_text(encoding="utf-8")
    assert 'id="select-all-charges" class="mobile-touch-target"' in participant_detail
    assert 'class="charge-checkbox mobile-touch-target"' in participant_detail
    assert 'id="select-all-audit-logs" class="mobile-touch-target"' in participant_detail
    assert 'class="audit-log-checkbox mobile-touch-target"' in participant_detail
    camp_detail = (TEMPLATES / "camp_detail.html").read_text(encoding="utf-8")
    assert 'name="price_attributes_confirmed" class="mobile-touch-target"' in camp_detail


def test_authentication_form_metadata_does_not_disable_autocomplete():
    form = EmailOrUsernameAuthenticationForm()
    username_widget = form.fields["username"].widget
    password_widget = form.fields["password"].widget

    assert username_widget.attrs.get("autocomplete") == "username"
    assert username_widget.attrs.get("autocomplete") != "off"
    assert username_widget.attrs.get("spellcheck") == "false"
    assert username_widget.attrs.get("autocapitalize") == "none"

    assert password_widget.attrs.get("autocomplete") == "current-password"
    assert password_widget.attrs.get("autocomplete") != "off"


def test_participant_and_enrollment_forms_have_semantic_input_metadata():
    for form_cls in (ParticipantForm, KioskSelfEnrollmentForm):
        form = form_cls()
        first_name_attrs = form.fields["first_name"].widget.attrs
        last_name_attrs = form.fields["last_name"].widget.attrs
        email_attrs = form.fields["email"].widget.attrs
        phone_attrs = form.fields["phone"].widget.attrs

        assert first_name_attrs.get("autocomplete") == "given-name"
        assert first_name_attrs.get("spellcheck") == "false"
        assert last_name_attrs.get("autocomplete") == "family-name"
        assert last_name_attrs.get("spellcheck") == "false"

        assert email_attrs.get("autocomplete") == "email"
        assert email_attrs.get("inputmode") == "email"
        assert email_attrs.get("spellcheck") == "false"

        assert phone_attrs.get("autocomplete") == "tel"
        assert phone_attrs.get("inputmode") == "tel"

        notes_attrs = form.fields["notes"].widget.attrs
        assert notes_attrs.get("spellcheck") == "true"
        assert notes_attrs.get("autocapitalize") == "sentences"


def test_family_member_form_has_name_metadata():
    form = ParticipantFamilyMemberForm()
    assert form.fields["first_name"].widget.attrs.get("autocomplete") == "given-name"
    assert form.fields["last_name"].widget.attrs.get("autocomplete") == "family-name"
    assert form.fields["email"].widget.attrs == {
        "autocomplete": "email",
        "inputmode": "email",
        "spellcheck": "false",
        "maxlength": "254",
    }
    assert form.fields["phone"].widget.attrs == {
        "autocomplete": "tel",
        "inputmode": "tel",
        "maxlength": "80",
    }


def test_booking_forms_have_explicit_names_labels_and_meaningful_metadata():
    quick_form = QuickBookingForm()
    assert list(quick_form.fields) == ["price_rule", "quantity"]
    assert quick_form.fields["price_rule"].label == "Artikel"
    assert quick_form.fields["quantity"].label == "Menge"
    assert quick_form.fields["price_rule"].widget.attrs == {}
    assert quick_form.fields["quantity"].widget.attrs == {
        "inputmode": "numeric",
        "min": 1,
        "max": 99,
        "step": "1",
    }

    meal_form = MealBookingForm()
    assert list(meal_form.fields) == ["meal_dates", "meal", "variant"]
    assert {name: field.label for name, field in meal_form.fields.items()} == {
        "meal_dates": "Lagertage",
        "meal": "Mahlzeit",
        "variant": "Variante",
    }
    for field_name in ("meal_dates", "meal", "variant"):
        assert "autocomplete" not in meal_form.fields[field_name].widget.attrs


@pytest.mark.django_db
def test_pin_inputs_have_numeric_inputmode_and_password_autocomplete():
    enrollment_form = KioskSelfEnrollmentForm()
    assert enrollment_form.fields["pin"].widget.attrs.get("inputmode") == "numeric"
    assert enrollment_form.fields["pin"].widget.attrs.get("autocomplete") == "new-password"

    login_form = KioskLoginForm()
    assert login_form.fields["pin"].widget.attrs.get("inputmode") == "numeric"
    assert login_form.fields["pin"].widget.attrs.get("autocomplete") == "current-password"


def test_monetary_inputs_have_decimal_inputmode():
    payment_form = PaymentForm()
    assert payment_form.fields["amount"].widget.attrs.get("inputmode") == "decimal"

    expense_form = ExpenseForm()
    assert expense_form.fields["amount"].widget.attrs.get("inputmode") == "decimal"
