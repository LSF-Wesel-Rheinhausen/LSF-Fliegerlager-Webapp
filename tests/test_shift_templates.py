import datetime

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from billing.models import Camp, DailyShiftTemplate, Shift, ShiftAssignment
from tests.factories import ParticipantFactory


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
def test_shift_template_create_persists_description(admin_client, active_camp):
    response = admin_client.post(
        reverse("shift-template-create", args=[active_camp.pk]),
        {
            "name": "Küchendienst",
            "description": "Arbeitsflächen reinigen und Vorräte prüfen.",
            "required_slots": 2,
            "is_active": True,
        },
    )
    assert response.status_code == 302
    template = DailyShiftTemplate.objects.get(camp=active_camp, name="Küchendienst")
    assert template.description == "Arbeitsflächen reinigen und Vorräte prüfen."


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
def test_shift_template_edit_persists_description(admin_client, active_camp):
    template = DailyShiftTemplate.objects.create(camp=active_camp, name="Küchendienst", required_slots=2)
    response = admin_client.post(
        reverse("shift-template-edit", args=[template.pk]),
        {"name": "Küchendienst", "description": "Neue Aufgabenbeschreibung", "required_slots": 3, "is_active": True},
    )
    assert response.status_code == 302
    template.refresh_from_db()
    assert template.description == "Neue Aufgabenbeschreibung"


@pytest.mark.django_db
def test_shift_templates_generate(admin_client, active_camp):
    DailyShiftTemplate.objects.create(
        camp=active_camp,
        name="Spüldienst",
        description="Geschirr spülen und Küche ordentlich hinterlassen.",
        required_slots=3,
    )
    DailyShiftTemplate.objects.create(camp=active_camp, name="Putzdienst", required_slots=2)

    url = reverse("shift-templates-generate", args=[active_camp.pk])
    response = admin_client.post(url)
    assert response.status_code == 302

    # 3 days total (starts_on to ends_on inclusive), 2 templates -> 6 shifts total
    assert Shift.objects.filter(camp=active_camp).count() == 6

    assert {shift.description for shift in Shift.objects.filter(camp=active_camp, name="Spüldienst")} == {
        "Geschirr spülen und Küche ordentlich hinterlassen."
    }


@pytest.mark.django_db
def test_shift_templates_generate_preserves_individual_description(admin_client, active_camp):
    template = DailyShiftTemplate.objects.create(
        camp=active_camp, name="Spüldienst", description="Vorlagenbeschreibung", required_slots=2
    )
    existing_shift = Shift.objects.create(
        camp=active_camp,
        date=active_camp.starts_on,
        name=template.name,
        description="Individuelle Beschreibung",
        required_slots=1,
    )
    response = admin_client.post(reverse("shift-templates-generate", args=[active_camp.pk]))
    assert response.status_code == 302
    existing_shift.refresh_from_db()
    assert existing_shift.description == "Individuelle Beschreibung"
    assert existing_shift.required_slots == 2


@pytest.mark.django_db
def test_shift_templates_generation_does_not_reduce_staffed_shift_capacity(admin_client, active_camp):
    template = DailyShiftTemplate.objects.create(
        camp=active_camp,
        name="Besetzter Dienst",
        required_slots=1,
    )
    existing_shift = Shift.objects.create(
        camp=active_camp,
        date=active_camp.starts_on,
        name=template.name,
        required_slots=2,
    )
    for index in range(2):
        ShiftAssignment.objects.create(
            shift=existing_shift,
            participant=ParticipantFactory(camp=active_camp, first_name=f"Eingeteilt{index}"),
        )
    existing_shift.refresh_from_db()
    revision_before = existing_shift.assignment_revision

    response = admin_client.post(reverse("shift-templates-generate", args=[active_camp.pk]))

    assert response.status_code == 302
    existing_shift.refresh_from_db()
    assert existing_shift.required_slots == 2
    assert existing_shift.assignment_revision == revision_before


@pytest.mark.django_db
def test_shift_save_allows_unchanged_persisted_overstaffed_capacity(active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        date=active_camp.starts_on,
        name="Bereits überbesetzt",
        required_slots=1,
    )
    for index in range(2):
        ShiftAssignment.objects.create(
            shift=shift,
            participant=ParticipantFactory(camp=active_camp, first_name=f"Überbesetzt{index}"),
        )

    shift.description = "Unabhängige Änderung"
    shift.save()

    shift.refresh_from_db()
    assert shift.required_slots == 1
    assert shift.description == "Unabhängige Änderung"


@pytest.mark.django_db
def test_shift_save_rejects_changed_capacity_below_existing_staffing(active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        date=active_camp.starts_on,
        name="Besetzter Dienst",
        required_slots=2,
    )
    ShiftAssignment.objects.create(shift=shift, participant=ParticipantFactory(camp=active_camp))

    shift.required_slots = 0
    with pytest.raises(ValidationError, match="Kapazität"):
        shift.save()
