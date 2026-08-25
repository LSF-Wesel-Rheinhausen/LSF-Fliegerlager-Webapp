import datetime
from decimal import Decimal

import pytest
from django.contrib import admin as django_admin
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.db.models.query import QuerySet
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from billing import admin as billing_admin
from billing import models, services, views
from billing.forms import ShiftForm
from billing.models import Participant, ParticipantFamilyMember, Settlement, Shift, ShiftAssignment, ShiftAuditLog
from billing.permissions import EDITOR_GROUP
from tests.factories import (
    CampFactory,
    GroupFactory,
    ParticipantFactory,
    ParticipantFamilyMemberFactory,
    SuperUserFactory,
    UserFactory,
)


@pytest.mark.django_db
def test_shift_assignment_audit_is_append_only_and_revisioned():
    assert hasattr(models, "ShiftAuditLog")
    ShiftAuditLog = models.ShiftAuditLog
    camp = CampFactory()
    shift = Shift.objects.create(camp=camp, name="Küchendienst", date="2026-08-24")
    admin = SuperUserFactory()

    assert shift.assignment_revision == 0
    audit_log = ShiftAuditLog.objects.create(
        shift=shift,
        camp=camp,
        changed_by=admin,
        action=ShiftAuditLog.Action.ADDED,
        identity_name_snapshot="Ada Lovelace",
        before={"assignment_revision": 0, "assigned_count": 0},
        after={"assignment_revision": 1, "assigned_count": 1},
    )

    audit_log.identity_name_snapshot = "Manipuliert"
    with pytest.raises(ValidationError, match="Audit-Einträge dürfen nicht verändert werden"):
        audit_log.save()
    with pytest.raises(ValidationError, match="Audit-Einträge dürfen nicht verändert werden"):
        ShiftAuditLog.objects.filter(pk=audit_log.pk).update(identity_name_snapshot="Manipuliert")
    with pytest.raises(ValidationError, match="Audit-Einträge dürfen nicht gelöscht werden"):
        ShiftAuditLog.objects.filter(pk=audit_log.pk).delete()


@pytest.mark.django_db
def test_shift_assignment_audit_keeps_shift_snapshot_after_shift_deletion():
    camp = CampFactory()
    shift = Shift.objects.create(camp=camp, name="Frühstücksdienst", date="2026-08-24")
    shift_id = shift.pk
    audit_log = ShiftAuditLog.objects.create(
        shift=shift,
        camp=camp,
        changed_by=SuperUserFactory(),
        action=ShiftAuditLog.Action.CAPACITY_OVERRIDE,
        before={"required_slots": 2},
        after={"required_slots": 1},
    )

    shift.delete()
    audit_log.refresh_from_db()

    assert audit_log.shift is None
    assert audit_log.shift_id_snapshot == shift_id
    assert audit_log.shift_name_snapshot == "Frühstücksdienst"
    assert audit_log.shift_date_snapshot == datetime.date(2026, 8, 24)
    assert audit_log.shift_reference == f"Frühstücksdienst am 24.08.2026 (#{shift_id})"


def test_shift_audit_admin_lists_immutable_shift_reference():
    assert "shift_reference" in billing_admin.ShiftAuditLogAdmin.list_display


@pytest.mark.django_db
def test_admin_adds_registered_participant_atomically_with_audit_and_revision():
    assert hasattr(services, "add_shift_assignment")
    camp = CampFactory()
    shift = Shift.objects.create(
        camp=camp,
        name="Küchendienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
        required_slots=2,
    )
    participant = ParticipantFactory(camp=camp, status=Participant.Status.REGISTERED)
    admin = SuperUserFactory()

    assignment = services.add_shift_assignment(
        shift_id=shift.pk,
        identity_token=f"participant-{participant.pk}",
        expected_revision=0,
        allow_over_capacity=False,
        confirm_historical=False,
        changed_by=admin,
    )

    shift.refresh_from_db()
    assert assignment == ShiftAssignment.objects.get(shift=shift, participant=participant)
    assert shift.assignment_revision == 1
    audit_log = ShiftAuditLog.objects.get()
    assert audit_log.action == ShiftAuditLog.Action.ADDED
    assert audit_log.changed_by == admin
    assert audit_log.identity_name_snapshot == participant.full_name
    assert audit_log.before == {"assignment_revision": 0, "assigned_count": 0}
    assert audit_log.after == {"assignment_revision": 1, "assigned_count": 1}
    assert audit_log.capacity_override is False
    assert audit_log.historical_override is False


@pytest.mark.django_db
def test_admin_add_locks_participant_before_shift_like_kiosk_signup(monkeypatch):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    shift = Shift.objects.create(
        camp=camp,
        name="Gemeinsame Lockreihenfolge",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    original_fetch_all = QuerySet._fetch_all
    locked_models = []

    def capture_select_for_update(queryset):
        if queryset._result_cache is None and queryset.query.select_for_update:
            locked_models.append(queryset.model)
        original_fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", capture_select_for_update)

    services.add_shift_assignment(
        shift_id=shift.pk,
        identity_token=f"participant-{participant.pk}",
        expected_revision=0,
        allow_over_capacity=False,
        confirm_historical=False,
        changed_by=SuperUserFactory(),
    )

    assert locked_models.index(Participant) < locked_models.index(Shift)


@pytest.mark.django_db
def test_admin_add_locks_guardian_and_companion_before_shift_like_kiosk_signup(monkeypatch):
    camp = CampFactory()
    guardian = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role=ParticipantFamilyMember.Role.COMPANION,
        is_active=True,
    )
    shift = Shift.objects.create(
        camp=camp,
        name="Begleitungs-Lockreihenfolge",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    original_fetch_all = QuerySet._fetch_all
    locked_models = []

    def capture_select_for_update(queryset):
        if queryset._result_cache is None and queryset.query.select_for_update:
            locked_models.append(queryset.model)
        original_fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", capture_select_for_update)

    services.add_shift_assignment(
        shift_id=shift.pk,
        identity_token=f"family-{companion.pk}",
        expected_revision=0,
        allow_over_capacity=False,
        confirm_historical=False,
        changed_by=SuperUserFactory(),
    )

    assert locked_models.index(Participant) < locked_models.index(ParticipantFamilyMember)
    assert locked_models.index(ParticipantFamilyMember) < locked_models.index(Shift)


@pytest.mark.django_db
def test_admin_adds_active_companion_as_operational_identity():
    camp = CampFactory()
    guardian = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role=ParticipantFamilyMember.Role.COMPANION,
        is_active=True,
    )
    shift = Shift.objects.create(
        camp=camp,
        name="Frühstück",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )

    assignment = services.add_shift_assignment(
        shift_id=shift.pk,
        identity_token=f"family-{companion.pk}",
        expected_revision=0,
        allow_over_capacity=False,
        confirm_historical=False,
        changed_by=SuperUserFactory(),
    )

    assert assignment.participant == guardian
    assert assignment.family_member == companion
    assert assignment.operational_display_name == companion.full_name
    assert ShiftAuditLog.objects.get().identity_name_snapshot == companion.full_name


@pytest.mark.django_db
def test_admin_removes_assignment_with_audit_and_revision():
    assert hasattr(services, "remove_shift_assignment")
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    shift = Shift.objects.create(
        camp=camp,
        name="Abenddienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
        assignment_revision=4,
    )
    assignment = ShiftAssignment.objects.create(shift=shift, participant=participant)
    admin = SuperUserFactory()

    services.remove_shift_assignment(
        shift_id=shift.pk,
        assignment_id=assignment.pk,
        expected_revision=5,
        confirm_historical=False,
        changed_by=admin,
    )

    shift.refresh_from_db()
    assert not ShiftAssignment.objects.filter(pk=assignment.pk).exists()
    assert shift.assignment_revision == 6
    audit_log = ShiftAuditLog.objects.get()
    assert audit_log.action == ShiftAuditLog.Action.REMOVED
    assert audit_log.identity_name_snapshot == participant.full_name
    assert audit_log.before == {"assignment_revision": 5, "assigned_count": 1}
    assert audit_log.after == {"assignment_revision": 6, "assigned_count": 0}


@pytest.mark.django_db
def test_admin_remove_locks_only_assignment_row_with_nullable_companion_join(monkeypatch):
    camp = CampFactory()
    guardian = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role=ParticipantFamilyMember.Role.COMPANION,
        is_active=True,
    )
    shift = Shift.objects.create(
        camp=camp,
        name="PostgreSQL-sichere Entfernung",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    assignment = ShiftAssignment.objects.create(
        shift=shift,
        participant=guardian,
        family_member=companion,
    )
    shift.refresh_from_db()
    original_fetch_all = QuerySet._fetch_all
    assignment_lock_targets = []

    def capture_select_for_update(queryset):
        if queryset.model is ShiftAssignment and queryset.query.select_for_update:
            assignment_lock_targets.append(queryset.query.select_for_update_of)
        original_fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", capture_select_for_update)

    services.remove_shift_assignment(
        shift_id=shift.pk,
        assignment_id=assignment.pk,
        expected_revision=shift.assignment_revision,
        confirm_historical=False,
        changed_by=SuperUserFactory(),
    )

    assert ("self",) in assignment_lock_targets


@pytest.mark.django_db
def test_assigned_companion_cannot_be_deleted_without_audited_removal_service():
    camp = CampFactory()
    guardian = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role=ParticipantFamilyMember.Role.COMPANION,
        is_active=True,
    )
    shift = Shift.objects.create(
        camp=camp,
        name="Geschützte Begleitung",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    assignment = ShiftAssignment.objects.create(
        shift=shift,
        participant=guardian,
        family_member=companion,
    )
    shift.refresh_from_db()

    with pytest.raises(ProtectedError):
        companion.delete()

    assert ShiftAssignment.objects.filter(pk=assignment.pk).exists()
    assert Shift.objects.get(pk=shift.pk).assignment_revision == shift.assignment_revision
    assert not ShiftAuditLog.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "participant_attributes",
    [
        {"status": Participant.Status.SETTLED},
        {"status": Participant.Status.CANCELLED},
        {"status": Participant.Status.PENDING_APPROVAL},
        {"status": Participant.Status.ACTIVE, "is_child": True},
        {"status": Participant.Status.ACTIVE, "archived_at": timezone.now()},
    ],
)
def test_admin_add_rejects_ineligible_participant_without_side_effect(participant_attributes):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, **participant_attributes)
    shift = Shift.objects.create(
        camp=camp,
        name="Sicherer Dienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )

    with pytest.raises(ValidationError, match="ausgewählte Person ist ungültig"):
        services.add_shift_assignment(
            shift_id=shift.pk,
            identity_token=f"participant-{participant.pk}",
            expected_revision=0,
            allow_over_capacity=False,
            confirm_historical=False,
            changed_by=SuperUserFactory(),
        )

    shift.refresh_from_db()
    assert shift.assignment_revision == 0
    assert not ShiftAssignment.objects.exists()
    assert not ShiftAuditLog.objects.exists()


@pytest.mark.django_db
def test_shift_assignment_model_rejects_cross_camp_identity():
    shift = Shift.objects.create(
        camp=CampFactory(name="Dienstlager"),
        name="Lagergrenze",
        date=timezone.localdate(),
    )
    foreign_participant = ParticipantFactory(camp=CampFactory(name="Fremdlager"))

    with pytest.raises(ValidationError, match="selben Lager"):
        ShiftAssignment.objects.create(shift=shift, participant=foreign_participant)


@pytest.mark.django_db
def test_admin_add_rejects_duplicate_without_revision_or_extra_audit():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    shift = Shift.objects.create(
        camp=camp,
        name="Doppelschutz",
        date=timezone.localdate() + datetime.timedelta(days=1),
        required_slots=2,
    )
    admin = SuperUserFactory()
    services.add_shift_assignment(
        shift_id=shift.pk,
        identity_token=f"participant-{participant.pk}",
        expected_revision=0,
        allow_over_capacity=False,
        confirm_historical=False,
        changed_by=admin,
    )

    with pytest.raises(ValidationError, match="bereits für diesen Dienst eingetragen"):
        services.add_shift_assignment(
            shift_id=shift.pk,
            identity_token=f"participant-{participant.pk}",
            expected_revision=1,
            allow_over_capacity=False,
            confirm_historical=False,
            changed_by=admin,
        )

    shift.refresh_from_db()
    assert shift.assignment_revision == 1
    assert ShiftAssignment.objects.filter(shift=shift, participant=participant).count() == 1
    assert ShiftAuditLog.objects.count() == 1


@pytest.mark.django_db
def test_admin_add_requires_and_audits_explicit_capacity_override():
    camp = CampFactory()
    existing = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    additional = ParticipantFactory(camp=camp, status=Participant.Status.REGISTERED)
    shift = Shift.objects.create(
        camp=camp,
        name="Voller Dienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
        required_slots=1,
    )
    ShiftAssignment.objects.create(shift=shift, participant=existing)
    admin = SuperUserFactory()

    with pytest.raises(ValidationError, match="Überbelegung ausdrücklich"):
        services.add_shift_assignment(
            shift_id=shift.pk,
            identity_token=f"participant-{additional.pk}",
            expected_revision=1,
            allow_over_capacity=False,
            confirm_historical=False,
            changed_by=admin,
        )
    assignment = services.add_shift_assignment(
        shift_id=shift.pk,
        identity_token=f"participant-{additional.pk}",
        expected_revision=1,
        allow_over_capacity=True,
        confirm_historical=False,
        changed_by=admin,
    )

    assert assignment.participant == additional
    assert ShiftAuditLog.objects.get().capacity_override is True


@pytest.mark.django_db
def test_past_shift_add_requires_and_audits_historical_confirmation():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    shift = Shift.objects.create(
        camp=camp,
        name="Vergangener Dienst",
        date=timezone.localdate() - datetime.timedelta(days=1),
    )
    admin = SuperUserFactory()

    with pytest.raises(ValidationError, match="historischer Bestätigung"):
        services.add_shift_assignment(
            shift_id=shift.pk,
            identity_token=f"participant-{participant.pk}",
            expected_revision=0,
            allow_over_capacity=False,
            confirm_historical=False,
            changed_by=admin,
        )
    services.add_shift_assignment(
        shift_id=shift.pk,
        identity_token=f"participant-{participant.pk}",
        expected_revision=0,
        allow_over_capacity=False,
        confirm_historical=True,
        changed_by=admin,
    )

    assert ShiftAuditLog.objects.get().historical_override is True


@pytest.mark.django_db
def test_settled_assignment_remove_requires_historical_confirmation():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, status=Participant.Status.SETTLED)
    shift = Shift.objects.create(
        camp=camp,
        name="Abgerechneter Dienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    assignment = ShiftAssignment.objects.create(shift=shift, participant=participant)
    admin = SuperUserFactory()

    with pytest.raises(ValidationError, match="historischer Bestätigung"):
        services.remove_shift_assignment(
            shift_id=shift.pk,
            assignment_id=assignment.pk,
            expected_revision=1,
            confirm_historical=False,
            changed_by=admin,
        )
    services.remove_shift_assignment(
        shift_id=shift.pk,
        assignment_id=assignment.pk,
        expected_revision=1,
        confirm_historical=True,
        changed_by=admin,
    )

    assert not ShiftAssignment.objects.filter(pk=assignment.pk).exists()
    assert ShiftAuditLog.objects.get().historical_override is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    "family_attributes",
    [
        {"role": ParticipantFamilyMember.Role.CHILD, "is_active": True},
        {"role": ParticipantFamilyMember.Role.COMPANION, "is_active": False},
    ],
)
def test_shift_assignment_model_rejects_ineligible_family_identity(family_attributes):
    camp = CampFactory()
    guardian = ParticipantFactory(camp=camp)
    family_member = ParticipantFamilyMemberFactory(guardian=guardian, **family_attributes)
    shift = Shift.objects.create(camp=camp, name="Familienprüfung", date=timezone.localdate())

    with pytest.raises(ValidationError, match="aktive Begleitpersonen"):
        ShiftAssignment.objects.create(shift=shift, participant=guardian, family_member=family_member)


@pytest.mark.django_db
def test_stale_assignment_revision_rejects_second_admin_change_without_side_effect():
    camp = CampFactory()
    first = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    second = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    shift = Shift.objects.create(
        camp=camp,
        name="Parallel",
        date=timezone.localdate() + datetime.timedelta(days=1),
        required_slots=2,
    )
    admin = SuperUserFactory()
    services.add_shift_assignment(
        shift_id=shift.pk,
        identity_token=f"participant-{first.pk}",
        expected_revision=0,
        allow_over_capacity=False,
        confirm_historical=False,
        changed_by=admin,
    )

    with pytest.raises(ValidationError, match="zwischenzeitlich geändert"):
        services.add_shift_assignment(
            shift_id=shift.pk,
            identity_token=f"participant-{second.pk}",
            expected_revision=0,
            allow_over_capacity=False,
            confirm_historical=False,
            changed_by=admin,
        )

    assert set(ShiftAssignment.objects.values_list("participant_id", flat=True)) == {first.pk}
    assert ShiftAuditLog.objects.count() == 1


@pytest.mark.django_db
def test_shift_edit_requires_explicit_confirmation_before_reducing_capacity_below_staffing(admin_client):
    camp = CampFactory()
    shift = Shift.objects.create(
        camp=camp,
        name="Kapazitätsdienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
        required_slots=2,
    )
    for index in range(2):
        ShiftAssignment.objects.create(
            shift=shift,
            participant=ParticipantFactory(camp=camp, first_name=f"Person{index}"),
        )

    response = admin_client.post(
        reverse("shift-edit", args=[shift.pk]),
        {
            "name": shift.name,
            "date": shift.date.isoformat(),
            "required_slots": 1,
            "assignment_revision": 2,
        },
    )

    shift.refresh_from_db()
    assert response.status_code == 200
    assert "Unterbesetzung ausdrücklich bestätigen" in response.content.decode()
    assert shift.required_slots == 2
    assert shift.assignment_revision == 2
    assert not ShiftAuditLog.objects.exists()


@pytest.mark.django_db
def test_shift_edit_audits_confirmed_capacity_reduction(admin_client):
    camp = CampFactory()
    shift = Shift.objects.create(
        camp=camp,
        name="Kapazitätsdienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
        required_slots=2,
    )
    for index in range(2):
        ShiftAssignment.objects.create(
            shift=shift,
            participant=ParticipantFactory(camp=camp, first_name=f"Person{index}"),
        )

    response = admin_client.post(
        reverse("shift-edit", args=[shift.pk]),
        {
            "name": shift.name,
            "date": shift.date.isoformat(),
            "required_slots": 1,
            "assignment_revision": 2,
            "confirm_over_capacity": "on",
        },
    )

    shift.refresh_from_db()
    assert response.status_code == 302
    assert shift.required_slots == 1
    assert shift.assignment_revision == 3
    audit_log = ShiftAuditLog.objects.get(action=ShiftAuditLog.Action.CAPACITY_OVERRIDE)
    assert audit_log.capacity_override is True
    assert audit_log.historical_override is False
    assert audit_log.before["required_slots"] == 2
    assert audit_log.after["required_slots"] == 1


@pytest.mark.django_db
def test_shift_form_rejects_capacity_below_existing_assignments_without_side_effects():
    camp = CampFactory()
    shift = Shift.objects.create(
        camp=camp,
        name="Geschützte Kapazität",
        date=timezone.localdate() + datetime.timedelta(days=1),
        required_slots=2,
    )
    for index in range(2):
        ShiftAssignment.objects.create(
            shift=shift,
            participant=ParticipantFactory(camp=camp, first_name=f"Besetzt{index}"),
        )

    form = ShiftForm(
        data={
            "name": shift.name,
            "date": shift.date.isoformat(),
            "required_slots": 1,
        },
        instance=shift,
    )

    assert not form.is_valid()
    assert "required_slots" in form.errors or "__all__" in form.errors
    shift.refresh_from_db()
    assert shift.required_slots == 2
    assert shift.assignment_revision == 2
    assert not ShiftAuditLog.objects.exists()


@pytest.mark.django_db
def test_past_shift_capacity_reduction_requires_and_audits_both_confirmations(admin_client):
    camp = CampFactory()
    shift = Shift.objects.create(
        camp=camp,
        name="Historischer Kapazitätsdienst",
        date=timezone.localdate() - datetime.timedelta(days=1),
        required_slots=2,
    )
    for index in range(2):
        ShiftAssignment.objects.create(
            shift=shift,
            participant=ParticipantFactory(camp=camp, first_name=f"Historisch{index}"),
        )

    payload = {
        "name": shift.name,
        "date": shift.date.isoformat(),
        "required_slots": 1,
        "assignment_revision": 2,
        "confirm_over_capacity": "on",
    }
    rejected_response = admin_client.post(reverse("shift-edit", args=[shift.pk]), payload)

    shift.refresh_from_db()
    assert rejected_response.status_code == 200
    assert "Historische Änderung ausdrücklich bestätigen" in rejected_response.content.decode()
    assert shift.required_slots == 2
    assert shift.assignment_revision == 2
    assert not ShiftAuditLog.objects.exists()

    accepted_response = admin_client.post(
        reverse("shift-edit", args=[shift.pk]),
        {**payload, "confirm_historical": "on"},
    )

    shift.refresh_from_db()
    assert accepted_response.status_code == 302
    assert shift.required_slots == 1
    assert shift.assignment_revision == 3
    audit_log = ShiftAuditLog.objects.get(action=ShiftAuditLog.Action.CAPACITY_OVERRIDE)
    assert audit_log.capacity_override is True
    assert audit_log.historical_override is True


@pytest.mark.django_db
def test_only_admin_can_add_shift_assignment_through_post_endpoint(client):
    camp = CampFactory()
    shift = Shift.objects.create(
        camp=camp,
        name="Admin-Dienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    participant = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    endpoint = f"/shifts/{shift.pk}/assignments/add/"
    payload = {
        "identity_token": f"participant-{participant.pk}",
        "expected_revision": 0,
    }
    editor = UserFactory()
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    client.force_login(editor)

    editor_response = client.post(endpoint, payload)
    assert editor_response.status_code == 302
    assert reverse("login") in editor_response.url
    assert not ShiftAssignment.objects.exists()

    admin = SuperUserFactory()
    client.force_login(admin)
    get_response = client.get(endpoint)
    assert get_response.status_code == 405
    response = client.post(endpoint, payload)

    assert response.status_code == 302
    assert response.url == reverse("shift-edit", args=[shift.pk])
    assert ShiftAssignment.objects.get().participant == participant


@pytest.mark.django_db
def test_shift_assignment_add_endpoint_enforces_csrf():
    camp = CampFactory()
    shift = Shift.objects.create(
        camp=camp,
        name="CSRF-Dienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    participant = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(SuperUserFactory())

    response = csrf_client.post(
        f"/shifts/{shift.pk}/assignments/add/",
        {"identity_token": f"participant-{participant.pk}", "expected_revision": 0},
    )

    assert response.status_code == 403
    assert not ShiftAssignment.objects.exists()


@pytest.mark.django_db
def test_shift_edit_admin_searches_only_eligible_same_camp_identities_with_no_js_forms(admin_client):
    camp = CampFactory()
    shift = Shift.objects.create(
        camp=camp,
        name="Suchdienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
        required_slots=3,
    )
    eligible = ParticipantFactory(
        camp=camp,
        first_name="Suchbar",
        last_name="Aktiv",
        status=Participant.Status.ACTIVE,
    )
    guardian = ParticipantFactory(camp=camp, first_name="Konto", status=Participant.Status.REGISTERED)
    companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        first_name="Suchbar",
        last_name="Begleitung",
        role=ParticipantFamilyMember.Role.COMPANION,
        is_active=True,
    )
    settled = ParticipantFactory(
        camp=camp,
        first_name="Suchbar",
        last_name="Abgerechnet",
        status=Participant.Status.SETTLED,
    )
    child = ParticipantFactory(camp=camp, first_name="Suchbar", last_name="Kind", is_child=True)
    foreign = ParticipantFactory(
        camp=CampFactory(name="Fremdlager"),
        first_name="Suchbar",
        last_name="Fremd",
        status=Participant.Status.ACTIVE,
    )

    response = admin_client.get(reverse("shift-edit", args=[shift.pk]), {"q": "Suchbar"})
    content = response.content.decode()

    assert response.status_code == 200
    assert "Ausführende Personen" in content
    assert f'value="participant-{eligible.pk}"' in content
    assert f'value="family-{companion.pk}"' in content
    assert settled.full_name not in content
    assert child.full_name not in content
    assert foreign.full_name not in content
    assert reverse("shift-assignment-add", args=[shift.pk]) in content
    assert "Überbelegung ausdrücklich bestätigen" in content


@pytest.mark.django_db
def test_rejected_assignment_add_preserves_validated_search_query(admin_client):
    camp = CampFactory()
    existing = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    candidate = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    shift = Shift.objects.create(
        camp=camp,
        name="Volle Suche",
        date=timezone.localdate() + datetime.timedelta(days=1),
        required_slots=1,
    )
    ShiftAssignment.objects.create(shift=shift, participant=existing)
    shift.refresh_from_db()

    response = admin_client.post(
        reverse("shift-assignment-add", args=[shift.pk]),
        {
            "identity_token": f"participant-{candidate.pk}",
            "expected_revision": shift.assignment_revision,
            "q": "Ada & Bob",
        },
    )

    assert response.status_code == 302
    assert response.url == f"{reverse('shift-edit', args=[shift.pk])}?q=Ada+%26+Bob"
    assert not ShiftAssignment.objects.filter(shift=shift, participant=candidate).exists()


@pytest.mark.django_db
def test_django_admin_shift_assignments_and_audit_are_read_only():
    assert hasattr(billing_admin, "ShiftAuditLogAdmin")
    request = RequestFactory().get("/admin/billing/shift/1/change/")
    request.user = SuperUserFactory()
    inline = billing_admin.ShiftAssignmentInline(Shift, django_admin.site)
    audit_admin = billing_admin.ShiftAuditLogAdmin(ShiftAuditLog, django_admin.site)

    assert inline.has_add_permission(request) is False
    assert inline.has_delete_permission(request) is False
    assert set(inline.get_readonly_fields(request)) >= {
        "participant",
        "family_member",
        "offered_for_exchange",
        "created_at",
        "updated_at",
    }
    assert audit_admin.has_add_permission(request) is False
    assert audit_admin.has_delete_permission(request) is False
    assert set(audit_admin.get_readonly_fields(request)) == {field.name for field in ShiftAuditLog._meta.fields}


@pytest.mark.django_db
def test_remove_endpoint_scopes_assignment_to_shift_and_admin(client):
    camp = CampFactory()
    first_shift = Shift.objects.create(
        camp=camp,
        name="Erster Dienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    second_shift = Shift.objects.create(
        camp=camp,
        name="Zweiter Dienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    participant = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    assignment = ShiftAssignment.objects.create(shift=second_shift, participant=participant)
    endpoint = reverse("shift-assignment-remove", args=[first_shift.pk, assignment.pk])
    editor = UserFactory()
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    client.force_login(editor)

    assert client.post(endpoint, {"expected_revision": 0}).status_code == 302
    assert ShiftAssignment.objects.filter(pk=assignment.pk).exists()

    client.force_login(SuperUserFactory())
    response = client.post(endpoint, {"expected_revision": 0, "confirm_removal": "on"}, follow=True)

    assert response.status_code == 200
    assert "Ungültige Zuordnung" in response.content.decode()
    assert ShiftAssignment.objects.filter(pk=assignment.pk).exists()
    assert not ShiftAuditLog.objects.exists()


@pytest.mark.django_db
def test_remove_endpoint_requires_explicit_confirmation_for_current_assignment(admin_client):
    camp = CampFactory()
    shift = Shift.objects.create(
        camp=camp,
        name="Bestätigte Entfernung",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    assignment = ShiftAssignment.objects.create(
        shift=shift,
        participant=ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE),
    )
    shift.refresh_from_db()

    response = admin_client.post(
        reverse("shift-assignment-remove", args=[shift.pk, assignment.pk]),
        {"expected_revision": shift.assignment_revision},
        follow=True,
    )

    assert response.status_code == 200
    assert "Entfernung ausdrücklich bestätigen" in response.content.decode()
    assert ShiftAssignment.objects.filter(pk=assignment.pk).exists()
    assert not ShiftAuditLog.objects.exists()


@pytest.mark.django_db
def test_assignment_audit_keeps_minimal_identity_snapshot_after_profile_changes():
    camp = CampFactory()
    participant = ParticipantFactory(
        camp=camp,
        first_name="Ada",
        last_name="Alt",
        email="private@example.test",
        phone="+49 123 456",
        status=Participant.Status.ACTIVE,
    )
    shift = Shift.objects.create(
        camp=camp,
        name="Auditdienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    services.add_shift_assignment(
        shift_id=shift.pk,
        identity_token=f"participant-{participant.pk}",
        expected_revision=0,
        allow_over_capacity=False,
        confirm_historical=False,
        changed_by=SuperUserFactory(),
    )

    Participant.objects.filter(pk=participant.pk).update(first_name="AdaNeu", email="changed@example.test")
    audit_log = ShiftAuditLog.objects.get()
    serialized_audit = f"{audit_log.before} {audit_log.after}"

    assert audit_log.identity_name_snapshot == "Ada Alt"
    assert "private@example.test" not in serialized_audit
    assert "+49 123 456" not in serialized_audit


@pytest.mark.django_db
def test_assignment_changes_progress_but_not_money_or_existing_settlement_snapshot():
    camp = CampFactory(shift_ratio_per_night=Decimal("0.2"))
    participant = ParticipantFactory(
        camp=camp,
        status=Participant.Status.ACTIVE,
        booked_nights=5,
    )
    shift = Shift.objects.create(
        camp=camp,
        name="Abrechnungsneutral",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    settlement = Settlement.objects.create(
        participant=participant,
        total_due=Decimal("12.34"),
        total_paid=Decimal("2.00"),
        total_advanced=Decimal("0.00"),
        balance=Decimal("10.34"),
        data={"immutable": "snapshot"},
    )
    before = services.calculate_participant_settlement(participant)

    services.add_shift_assignment(
        shift_id=shift.pk,
        identity_token=f"participant-{participant.pk}",
        expected_revision=0,
        allow_over_capacity=False,
        confirm_historical=False,
        changed_by=SuperUserFactory(),
    )

    participant.refresh_from_db()
    settlement.refresh_from_db()
    after = services.calculate_participant_settlement(participant)
    assert participant.completed_shifts == 1
    assert after.total_due == before.total_due
    assert after.balance == before.balance
    assert settlement.total_due == Decimal("12.34")
    assert settlement.balance == Decimal("10.34")
    assert settlement.data == {"immutable": "snapshot"}


@pytest.mark.django_db
def test_shift_edit_staffing_context_has_fixed_query_budget(django_assert_num_queries):
    camp = CampFactory()
    shift = Shift.objects.create(camp=camp, name="Querydienst", date=timezone.localdate())
    for index in range(5):
        participant = ParticipantFactory(
            camp=camp,
            first_name=f"Suchperson{index}",
            status=Participant.Status.ACTIVE,
        )
        ShiftAssignment.objects.create(shift=shift, participant=participant)
    request = RequestFactory().get(reverse("shift-edit", args=[shift.pk]), {"q": "Suchperson"})
    request.user = SuperUserFactory()

    with django_assert_num_queries(3):
        context = views._shift_edit_context(request, shift, ShiftForm(instance=shift))
        assert len(context["assignments"]) == 5


@pytest.mark.django_db
def test_kiosk_style_identity_change_invalidates_stale_admin_revision():
    camp = CampFactory()
    original = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    replacement = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    shift = Shift.objects.create(
        camp=camp,
        name="Tauschdienst",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    assignment = ShiftAssignment.objects.create(shift=shift, participant=original)
    shift.refresh_from_db()
    revision_before_takeover = shift.assignment_revision
    assignment.participant = replacement
    assignment.save(update_fields=["participant", "updated_at"])

    shift.refresh_from_db()
    assert shift.assignment_revision == revision_before_takeover + 1
    with pytest.raises(ValidationError, match="zwischenzeitlich geändert"):
        services.remove_shift_assignment(
            shift_id=shift.pk,
            assignment_id=assignment.pk,
            expected_revision=revision_before_takeover,
            confirm_historical=False,
            changed_by=SuperUserFactory(),
        )
    assert ShiftAssignment.objects.get(pk=assignment.pk).participant == replacement


@pytest.mark.django_db
def test_service_rejects_editor_even_with_valid_ids():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    shift = Shift.objects.create(
        camp=camp,
        name="Adminschutz",
        date=timezone.localdate() + datetime.timedelta(days=1),
    )
    editor = UserFactory()
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))

    with pytest.raises(ValidationError, match="Nur Administratoren"):
        services.add_shift_assignment(
            shift_id=shift.pk,
            identity_token=f"participant-{participant.pk}",
            expected_revision=0,
            allow_over_capacity=False,
            confirm_historical=False,
            changed_by=editor,
        )
    assert not ShiftAssignment.objects.exists()
    assert not ShiftAuditLog.objects.exists()


@pytest.mark.django_db
def test_past_shift_remove_requires_historical_confirmation():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, status=Participant.Status.ACTIVE)
    shift = Shift.objects.create(
        camp=camp,
        name="Vergangene Entfernung",
        date=timezone.localdate() - datetime.timedelta(days=1),
    )
    assignment = ShiftAssignment.objects.create(shift=shift, participant=participant)
    shift.refresh_from_db()

    with pytest.raises(ValidationError, match="historischer Bestätigung"):
        services.remove_shift_assignment(
            shift_id=shift.pk,
            assignment_id=assignment.pk,
            expected_revision=shift.assignment_revision,
            confirm_historical=False,
            changed_by=SuperUserFactory(),
        )
    assert ShiftAssignment.objects.filter(pk=assignment.pk).exists()


@pytest.mark.django_db
def test_shift_create_does_not_show_staffing_override_controls(admin_client):
    camp = CampFactory()

    response = admin_client.get(reverse("shift-create", args=[camp.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Unterbesetzung ausdrücklich bestätigen" not in content
    assert 'name="assignment_revision"' not in content
