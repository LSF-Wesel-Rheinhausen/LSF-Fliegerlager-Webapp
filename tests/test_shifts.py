import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from billing.models import Camp, Participant, ParticipantFamilyMember, Shift, ShiftAssignment


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
def test_shift_report_ranks_regular_companions_by_their_own_assignments(admin_client, active_camp):
    active_camp.shift_ratio_per_night = Decimal("0.2")
    active_camp.save(update_fields=["shift_ratio_per_night", "updated_at"])
    companion = Participant.objects.create(
        camp=active_camp,
        first_name="Regular",
        last_name="Companion",
        is_companion=True,
        booked_nights=5,
    )
    shift = Shift.objects.create(camp=active_camp, name="Companion Duty", date=datetime.date.today())
    ShiftAssignment.objects.create(shift=shift, participant=companion)

    response = admin_client.get(reverse("shift-report", args=[active_camp.pk]))

    assert response.status_code == 200
    ranked = {participant.full_name: participant for participant in response.context["participants"]}
    assert ranked[companion.full_name].completed_shifts == 1
    assert ranked[companion.full_name].target_shifts == 1


@pytest.mark.django_db
def test_shift_report_ranks_guardian_companion_as_own_identity_without_guardian_attribution(admin_client, active_camp):
    active_camp.shift_ratio_per_night = Decimal("0.2")
    active_camp.save(update_fields=["shift_ratio_per_night", "updated_at"])
    guardian = Participant.objects.create(
        camp=active_camp, first_name="Guardian", last_name="Account", booked_nights=10
    )
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Family",
        last_name="Companion",
        role=ParticipantFamilyMember.Role.COMPANION,
        arrival_date=datetime.date.today(),
        departure_date=datetime.date.today() + datetime.timedelta(days=5),
    )
    shift = Shift.objects.create(camp=active_camp, name="Family Duty", date=datetime.date.today())
    ShiftAssignment.objects.create(shift=shift, participant=guardian, family_member=companion)

    response = admin_client.get(reverse("shift-report", args=[active_camp.pk]))

    assert response.status_code == 200
    ranked = {participant.full_name: participant for participant in response.context["participants"]}
    assert companion.full_name in ranked
    assert ranked[companion.full_name].completed_shifts == 1
    assert ranked[companion.full_name].target_shifts == 1
    assert ranked[guardian.full_name].completed_shifts == 0


@pytest.mark.django_db
def test_shift_report_excludes_regular_and_guardian_family_children_without_targets(admin_client, active_camp):
    regular_child = Participant.objects.create(
        camp=active_camp,
        first_name="Regular",
        last_name="Child",
        is_child=True,
        booked_nights=10,
    )
    guardian = Participant.objects.create(camp=active_camp, first_name="Child", last_name="Guardian")
    family_child = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Family",
        last_name="Child",
        role=ParticipantFamilyMember.Role.CHILD,
        arrival_date=datetime.date.today(),
        departure_date=datetime.date.today() + datetime.timedelta(days=10),
    )

    response = admin_client.get(reverse("shift-report", args=[active_camp.pk]))

    assert response.status_code == 200
    ranked_names = {participant.full_name for participant in response.context["participants"]}
    assert regular_child.full_name not in ranked_names
    assert family_child.full_name not in ranked_names
    assert regular_child.target_shifts == 0
    assert family_child.target_shifts == 0


@pytest.mark.django_db
def test_shift_manage_renders_companion_identity_for_assignment(admin_client, active_camp):
    guardian = Participant.objects.create(camp=active_camp, first_name="Guardian", last_name="Account")
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Visible",
        last_name="Companion",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    shift = Shift.objects.create(camp=active_camp, name="Managed Duty", date=datetime.date.today())
    ShiftAssignment.objects.create(shift=shift, participant=guardian, family_member=companion)

    response = admin_client.get(reverse("shift-manage", args=[active_camp.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert companion.full_name in content
    assert f">{guardian.full_name}</a>" not in content


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
def test_admin_can_bulk_delete_shifts(admin_client, active_camp):
    s1 = Shift.objects.create(camp=active_camp, name="Dienst 1", date=datetime.date.today(), required_slots=1)
    s2 = Shift.objects.create(camp=active_camp, name="Dienst 2", date=datetime.date.today(), required_slots=1)
    s3 = Shift.objects.create(camp=active_camp, name="Dienst 3", date=datetime.date.today(), required_slots=1)

    url = reverse("shift-bulk-delete", args=[active_camp.pk])
    response = admin_client.post(url, {"shift_ids": [s1.pk, s2.pk]})
    assert response.status_code == 302
    assert not Shift.objects.filter(pk__in=[s1.pk, s2.pk]).exists()
    assert Shift.objects.filter(pk=s3.pk).exists()


@pytest.mark.django_db
def test_bulk_delete_empty_selection_warning(admin_client, active_camp):
    url = reverse("shift-bulk-delete", args=[active_camp.pk])
    response = admin_client.post(url, {})
    assert response.status_code == 302


@pytest.mark.django_db
def test_bulk_delete_scoped_to_camp(admin_client, active_camp, db):
    other_camp = Camp.objects.create(
        name="Other Camp",
        year=2026,
        starts_on=datetime.date.today(),
        ends_on=datetime.date.today() + datetime.timedelta(days=5),
        is_active=True,
    )
    s_other = Shift.objects.create(camp=other_camp, name="Other Shift", date=datetime.date.today(), required_slots=1)

    url = reverse("shift-bulk-delete", args=[active_camp.pk])
    response = admin_client.post(url, {"shift_ids": [s_other.pk]})
    assert response.status_code == 302
    assert Shift.objects.filter(pk=s_other.pk).exists()


@pytest.mark.django_db
def test_bulk_delete_rejects_non_numeric_shift_id_without_deleting_valid_selection(admin_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Dienst",
        date=datetime.date.today(),
        required_slots=1,
    )

    response = admin_client.post(
        reverse("shift-bulk-delete", args=[active_camp.pk]),
        {"shift_ids": [shift.pk, "not-an-id"]},
    )

    assert response.status_code == 302
    assert Shift.objects.filter(pk=shift.pk).exists()


@pytest.mark.django_db
def test_generate_shifts_from_templates(admin_client, active_camp):
    from billing.models import DailyShiftException, DailyShiftTemplate

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
