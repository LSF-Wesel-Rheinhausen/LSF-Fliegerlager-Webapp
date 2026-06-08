import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from billing.models import Camp, Participant, Shift


@pytest.fixture
def active_camp(db):
    return Camp.objects.create(
        name="Test Camp",
        year=datetime.date.today().year,
        starts_on=datetime.date.today() - datetime.timedelta(days=1),
        ends_on=datetime.date.today() + datetime.timedelta(days=10),
        is_active=True,
    )


@pytest.fixture
def shift(db, admin_client, active_camp):
    return Shift.objects.create(
        camp=active_camp,
        name="Frühstücksdienst",
        date=datetime.date.today() + datetime.timedelta(days=1),
        required_slots=2,
    )


@pytest.mark.django_db
def test_target_shifts_calculation(active_camp):
    active_camp.shift_ratio_per_night = Decimal("0.2")
    active_camp.save()
    p1 = Participant.objects.create(camp=active_camp, first_name="A", last_name="B", booked_nights=5)
    assert p1.target_shifts == 1
    p2 = Participant.objects.create(camp=active_camp, first_name="C", last_name="D", booked_nights=7)
    assert p2.target_shifts == 1
    p3 = Participant.objects.create(camp=active_camp, first_name="E", last_name="F", booked_nights=8)
    assert p3.target_shifts == 2


@pytest.mark.django_db
def test_admin_can_create_shift(admin_client, active_camp):
    url = reverse("shift-create", args=[active_camp.pk])
    response = admin_client.post(
        url,
        {
            "name": "Klodienst",
            "date": "2026-08-01",
            "required_slots": 1,
        },
    )
    assert response.status_code == 302
    assert Shift.objects.filter(name="Klodienst").exists()


@pytest.mark.django_db
def test_admin_can_delete_shift(admin_client, shift):
    url = reverse("shift-delete", args=[shift.pk])
    response = admin_client.post(url)
    assert response.status_code == 302
    assert not Shift.objects.filter(pk=shift.pk).exists()


@pytest.mark.django_db
def test_generate_shifts_from_templates(admin_client, active_camp):
    from billing.models import DailyShiftTemplate, DailyShiftException

    template = DailyShiftTemplate.objects.create(
        camp=active_camp,
        name="Abendessen kochen",
        required_slots=3,
    )
    
    # Create exception to skip the first day
    DailyShiftException.objects.create(
        template=template,
        date=active_camp.starts_on,
        is_skipped=True,
    )

    # Create exception to reduce slots on the last day
    DailyShiftException.objects.create(
        template=template,
        date=active_camp.ends_on,
        custom_required_slots=1,
    )

    url = reverse("admin:billing_dailyshifttemplate_changelist")
    response = admin_client.post(
        url,
        {
            "action": "generate_shifts_for_templates",
            "_selected_action": [template.pk],
        },
    )

    assert response.status_code == 302
    # Active camp spans 12 days (starts_on to ends_on)
    # One day is skipped, so 11 shifts should be generated
    assert Shift.objects.filter(name="Abendessen kochen").count() == 11
    
    # Check the exception day slots
    last_day_shift = Shift.objects.get(name="Abendessen kochen", date=active_camp.ends_on)
    assert last_day_shift.required_slots == 1
