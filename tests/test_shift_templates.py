import datetime

import pytest
from django.urls import reverse

from billing.models import Camp, DailyShiftTemplate, Shift


@pytest.fixture
def active_camp(db):
    return Camp.objects.create(
        name="Test Camp",
        year=datetime.date.today().year,
        starts_on=datetime.date.today(),
        ends_on=datetime.date.today() + datetime.timedelta(days=2),
        is_active=True,
    )


@pytest.mark.django_db
def test_shift_templates_manage_view(admin_client, active_camp):
    url = reverse("shift-templates-manage", args=[active_camp.pk])
    response = admin_client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_shift_template_create(admin_client, active_camp):
    url = reverse("shift-template-create", args=[active_camp.pk])
    data = {
        "name": "Spüldienst",
        "required_slots": 3,
        "is_active": True,
    }
    response = admin_client.post(url, data)
    assert response.status_code == 302
    assert DailyShiftTemplate.objects.filter(camp=active_camp, name="Spüldienst").exists()


@pytest.mark.django_db
def test_shift_template_edit(admin_client, active_camp):
    template = DailyShiftTemplate.objects.create(camp=active_camp, name="Old Name", required_slots=2)
    url = reverse("shift-template-edit", args=[template.pk])
    data = {
        "name": "New Name",
        "required_slots": 5,
        "is_active": True,
    }
    response = admin_client.post(url, data)
    assert response.status_code == 302
    template.refresh_from_db()
    assert template.name == "New Name"
    assert template.required_slots == 5


@pytest.mark.django_db
def test_shift_templates_generate(admin_client, active_camp):
    DailyShiftTemplate.objects.create(camp=active_camp, name="Spüldienst", required_slots=3)
    DailyShiftTemplate.objects.create(camp=active_camp, name="Putzdienst", required_slots=2)

    url = reverse("shift-templates-generate", args=[active_camp.pk])
    response = admin_client.post(url)
    assert response.status_code == 302

    # 3 days total (starts_on to ends_on inclusive), 2 templates -> 6 shifts total
    assert Shift.objects.filter(camp=active_camp).count() == 6
