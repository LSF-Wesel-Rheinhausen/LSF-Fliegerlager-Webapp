import re
from datetime import date

import pytest
from django.template.loader import render_to_string
from django.urls import reverse

from billing.kiosk_access import KIOSK_PARTICIPANT_SESSION_KEY
from billing.models import AttendanceDay
from billing.profile_forms import ParticipantProfileForm
from tests.factories import CampFactory, ParticipantFactory


@pytest.mark.django_db
def test_admin_attendance_matrix_is_scrollable_and_uses_explicit_table_semantics(admin_client):
    camp = CampFactory(starts_on=date(2025, 7, 1), ends_on=date(2025, 7, 4))
    participant = ParticipantFactory(
        camp=camp,
        first_name="Ada",
        last_name="Lovelace",
        arrival_date=date(2025, 7, 1),
        departure_date=date(2025, 7, 3),
    )
    AttendanceDay.objects.create(
        participant=participant,
        date=date(2025, 7, 2),
        is_present=False,
    )

    response = admin_client.get(reverse("camp-attendance-overview", args=[camp.pk]))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'class="kiosk-table__wrapper attendance-matrix-scroll"' in content
    assert 'tabindex="0"' in content
    assert 'role="region"' in content
    assert 'aria-label="Anwesenheitsmatrix"' in content
    assert '<th id="attendance-person-heading" scope="col">Person</th>' in content
    assert '<th id="attendance-day-20250701" scope="col">01.07.2025</th>' in content
    assert re.search(
        r'<th id="attendance-person-\d+" scope="row">Ada Lovelace</th>',
        content,
    )
    assert 'headers="attendance-person-' in content
    assert "attendance-day-20250701" in content
    assert "Anwesend" in content
    assert "Abwesend" in content
    assert "Außerhalb des Aufenthalts" in content
    assert "Legende" in content


@pytest.mark.django_db
def test_kiosk_profile_errors_are_associated_with_invalid_controls():
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    form = ParticipantProfileForm(
        {
            "first_name": "",
            "last_name": "Lovelace",
            "email": "not-an-email",
            "phone": "",
            "birth_date": "2099-01-01",
        },
        instance=participant,
    )
    assert not form.is_valid()

    content = render_to_string(
        "billing/kiosk_profile.html",
        {
            "participant": participant,
            "form": form,
            "managed_family_members": [],
            "kiosk_mode": "private",
            "kiosk_urls": {"home": "/kiosk/", "logout": "/kiosk/logout/", "login": "/kiosk/login/"},
        },
    )
    assert " novalidate" not in content
    assert '<form method="post" class="kiosk-profile-form">' in content
    assert content.count('class="form-group kiosk-profile-form__field') == len(form.fields)
    assert 'class="button-row kiosk-profile-form__actions"' in content
    for field in form:
        assert f'<label for="{field.id_for_label}">{field.label}</label>' in content
    assert re.search(
        r'<input(?=[^>]*\bid="id_first_name")(?=[^>]*\baria-invalid="true")'
        r'(?=[^>]*\baria-describedby="id_first_name_error")[^>]*>',
        content,
    )
    assert 'id="id_first_name_error"' in content
    assert 'role="alert"' in content


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("starts_on", "ends_on"),
    [(None, None), (date(2025, 7, 4), date(2025, 7, 1))],
)
def test_admin_attendance_overview_explains_missing_or_invalid_camp_dates(admin_client, starts_on, ends_on):
    camp = CampFactory(starts_on=starts_on, ends_on=ends_on)

    response = admin_client.get(reverse("camp-attendance-overview", args=[camp.pk]))

    assert response.status_code == 200
    assert "Lagerzeitraum fehlt oder ist ungültig" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_kiosk_home_explains_missing_camp_dates(kiosk_client):
    camp = CampFactory(starts_on=None, ends_on=None)
    participant = ParticipantFactory(camp=camp)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert "Check-in derzeit nicht verfügbar" in response.content.decode("utf-8")
