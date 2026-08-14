import pytest

from billing.email_delivery import _html_body
from billing.forms import EmailOrUsernameAuthenticationForm, KioskSelfEnrollmentForm


def test_html_email_template_structure_and_contrast():
    html = _html_body("Hallo World\nEssen gebucht.")
    assert '<html lang="de">' in html
    assert "font-family: system-ui" in html
    assert "color: #1a2027" in html
    assert "max-width: 600px" in html
    assert "Hallo World<br>Essen gebucht." in html


def test_form_validation_adds_aria_invalid_and_describedby():
    form = EmailOrUsernameAuthenticationForm(data={"username": "", "password": ""})
    assert not form.is_valid()

    form.add_error("username", "Dieses Feld ist erforderlich.")
    username_attrs = form.fields["username"].widget.attrs

    assert username_attrs.get("aria-invalid") == "true"
    assert username_attrs.get("aria-describedby") == "id_username_error"


@pytest.mark.django_db
def test_kiosk_enrollment_form_errors_decorate_aria_attributes():
    form = KioskSelfEnrollmentForm(data={"pin": "1234", "pin_repeat": "9999"})
    assert not form.is_valid()
    form.clean()

    pin_repeat_attrs = form.fields["pin_repeat"].widget.attrs
    assert pin_repeat_attrs.get("aria-invalid") == "true"
    assert pin_repeat_attrs.get("aria-describedby") == "id_pin_repeat_error"
