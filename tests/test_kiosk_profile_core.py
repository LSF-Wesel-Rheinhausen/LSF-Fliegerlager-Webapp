from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.test import RequestFactory
from django.utils import timezone

import billing.profile_forms as profile_forms
from billing.kiosk_access import KIOSK_FAMILY_MEMBER_SESSION_KEY, KIOSK_PARTICIPANT_SESSION_KEY
from billing.models import KioskActionAuditLog, Participant, ParticipantFamilyMember
from tests.factories import ParticipantFactory, ParticipantFamilyMemberFactory


def _request(method, path, *, data, participant=None, family_member=None):
    request = getattr(RequestFactory(), method)(path, data=data)
    request.session = {}
    if participant is not None:
        request.session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    if family_member is not None:
        request.session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = family_member.pk
    return request


@pytest.mark.django_db
def test_participant_profile_form_whitelists_and_normalizes_contact_fields():
    participant = ParticipantFactory(first_name="Old", last_name="Name", email="old@example.test", phone="0")
    form = profile_forms.ParticipantProfileForm(
        {
            "first_name": "  Ada  ",
            "last_name": "  Lovelace ",
            "email": "ada@example.test",
            "phone": "+49 111",
            "birth_date": "1990-01-02",
            "status": Participant.Status.CANCELLED,
            "notes": "forged",
        },
        instance=participant,
    )

    assert set(form.fields) == {"first_name", "last_name", "email", "phone", "birth_date"}
    assert form.is_valid(), form.errors
    saved = form.save()
    saved.refresh_from_db()
    assert (saved.first_name, saved.last_name, saved.email, saved.phone, saved.birth_date) == (
        "Ada",
        "Lovelace",
        "ada@example.test",
        "+49 111",
        date(1990, 1, 2),
    )
    assert saved.status != Participant.Status.CANCELLED
    assert saved.notes != "forged"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "data,field",
    [
        ({"first_name": "   ", "last_name": "Valid"}, "first_name"),
        ({"first_name": "Valid", "last_name": "   "}, "last_name"),
    ],
)
def test_profile_form_rejects_blank_names(data, field):
    form = profile_forms.ParticipantProfileForm(data, instance=ParticipantFactory())

    assert not form.is_valid()
    assert field in form.errors


@pytest.mark.django_db
def test_profile_form_rejects_birth_date_after_configured_local_date(monkeypatch):
    local_today = date(2026, 7, 2)
    monkeypatch.setattr(profile_forms.timezone, "localdate", lambda: local_today)
    form = profile_forms.ParticipantProfileForm(
        {
            "first_name": "Future",
            "last_name": "Date",
            "birth_date": str(local_today + timedelta(days=1)),
        },
        instance=ParticipantFactory(),
    )

    assert not form.is_valid()
    assert "birth_date" in form.errors


@pytest.mark.django_db
def test_profile_form_uses_configured_local_date_at_midnight_boundary(monkeypatch):
    monkeypatch.setattr(profile_forms, "timezone", SimpleNamespace(localdate=lambda: date(2026, 7, 2)), raising=False)
    monkeypatch.setattr(profile_forms, "date", SimpleNamespace(today=lambda: date(2026, 7, 1)), raising=False)
    form = profile_forms.ParticipantProfileForm(
        {"first_name": "Local", "last_name": "Midnight", "birth_date": "2026-07-02"},
        instance=ParticipantFactory(),
    )

    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_profile_form_rejects_case_insensitive_same_camp_participant_name_collision():
    participant = ParticipantFactory(first_name="Original", last_name="Person")
    ParticipantFactory(camp=participant.camp, first_name="Existing", last_name="Name")

    form = profile_forms.ParticipantProfileForm(
        {"first_name": " existing ", "last_name": " NAME "},
        instance=participant,
    )

    assert not form.is_valid()
    assert "first_name" in form.errors


@pytest.mark.django_db
def test_primary_profile_view_updates_only_the_authenticated_participant_and_audits_safe_field_names():
    from billing.profile_views import kiosk_profile

    participant = ParticipantFactory(email="old@example.test", phone="0")
    request = _request(
        "post",
        f"/kiosk/profile/{participant.pk}/",
        participant=participant,
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.test",
            "phone": "+49 111",
            "birth_date": "1990-01-02",
            "arrival_date": "2999-01-01",
        },
    )

    response = kiosk_profile(request, participant.pk)

    assert response.status_code == 302
    participant.refresh_from_db()
    assert participant.arrival_date is None
    audit = KioskActionAuditLog.objects.get(target_participant=participant)
    assert audit.action == KioskActionAuditLog.Action.PROFILE_UPDATED
    assert audit.before == {"changed_fields": ["first_name", "last_name", "email", "phone", "birth_date"]}
    assert audit.after == {"changed_fields": ["first_name", "last_name", "email", "phone", "birth_date"]}
    assert "ada@example.test" not in audit.description
    assert "+49 111" not in audit.description


@pytest.mark.django_db
def test_companion_can_edit_only_its_own_active_family_profile():
    from billing.profile_views import kiosk_family_member_profile

    guardian = ParticipantFactory()
    companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role=ParticipantFamilyMember.Role.COMPANION,
        first_name="Old",
    )
    other_member = ParticipantFamilyMemberFactory(guardian=guardian)
    request = _request(
        "post",
        f"/kiosk/family/{companion.pk}/profile/",
        participant=guardian,
        family_member=companion,
        data={"first_name": "New", "last_name": companion.last_name},
    )

    own_response = kiosk_family_member_profile(request, companion.pk)
    forbidden_response = kiosk_family_member_profile(request, other_member.pk)

    assert own_response.status_code == 302
    assert forbidden_response.status_code == 403
    companion.refresh_from_db()
    assert companion.first_name == "New"


@pytest.mark.django_db
def test_guardian_can_edit_only_its_own_family_member_and_stale_identity_is_rejected():
    from billing.profile_views import kiosk_family_member_profile, kiosk_profile

    guardian = ParticipantFactory()
    child = ParticipantFamilyMemberFactory(guardian=guardian, first_name="Child")
    partner = ParticipantFactory(camp=guardian.camp)
    guardian_request = _request(
        "post",
        f"/kiosk/family/{child.pk}/profile/",
        participant=guardian,
        data={"first_name": "Updated", "last_name": child.last_name},
    )
    stale_request = _request("post", f"/kiosk/profile/{guardian.pk}/", participant=guardian, data={})

    child_response = kiosk_family_member_profile(guardian_request, child.pk)
    partner_response = kiosk_profile(guardian_request, partner.pk)
    guardian.archived_at = timezone.now()
    guardian.save(update_fields=["archived_at"])
    stale_response = kiosk_profile(stale_request, guardian.pk)

    assert child_response.status_code == 302
    assert partner_response.status_code == 403
    assert stale_response.status_code == 302
    child.refresh_from_db()
    assert child.first_name == "Updated"
