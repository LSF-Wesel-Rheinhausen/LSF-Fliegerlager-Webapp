from pathlib import Path

import pytest

from billing.forms import (
    EmailOrUsernameAuthenticationForm,
    ExpenseForm,
    KioskFamilyMemberForm,
    KioskLoginForm,
    KioskSelfEnrollmentForm,
    ParticipantFamilyMemberForm,
    ParticipantForm,
    PaymentForm,
)


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


def test_family_member_form_has_name_metadata():
    form = ParticipantFamilyMemberForm()
    assert form.fields["first_name"].widget.attrs.get("autocomplete") == "given-name"
    assert form.fields["last_name"].widget.attrs.get("autocomplete") == "family-name"


def test_kiosk_family_member_form_has_name_metadata():
    form = KioskFamilyMemberForm()
    assert form.fields["first_name"].widget.attrs.get("autocomplete") == "given-name"
    assert form.fields["last_name"].widget.attrs.get("autocomplete") == "family-name"


def test_mobile_css_covers_standalone_controls_and_table_actions():
    css = (Path(__file__).parents[1] / "src/static/billing/app-v8.css").read_text(encoding="utf-8")
    assert 'input[type="checkbox"]' in css
    assert 'input[type="radio"]' in css
    assert "min-width: 44px" in css
    assert ".row-actions a" in css
    assert ".table-actions a" in css


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
