import json
import re
from datetime import date
from hashlib import sha256

import pytest
from django.core import signing
from django.db import connection
from django.db.models import Prefetch
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from billing.kiosk_access import KIOSK_FAMILY_MEMBER_SESSION_KEY, KIOSK_PARTICIPANT_SESSION_KEY
from billing.models import (
    AttendanceDay,
    KioskActionAuditLog,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
)
from billing.permissions import EDITOR_GROUP
from billing.views import _kiosk_attendance_fingerprint, _kiosk_checkin_original_state, _sign_kiosk_checkin_state
from tests.factories import (
    CampFactory,
    GroupFactory,
    ParticipantFactory,
    ParticipantFamilyMemberFactory,
    SuperUserFactory,
    UserFactory,
)


def _set_kiosk_identity(client, *, participant=None, family_member=None):
    session = client.session
    if family_member is not None and participant is None:
        participant = family_member.guardian
    if participant is not None:
        session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    if family_member is not None:
        session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = family_member.pk
    session.save()


def _profile_url(route_name, participant):
    return reverse(route_name, kwargs={"participant_id": participant.pk})


def _checkin_targets(kiosk_client):
    response = kiosk_client.get(reverse("kiosk-home"))
    assert response.status_code in {200, 400}
    return {target["token"]: target for target in response.context["checkin_participants"]}, response


def _attendance_payload(target, *, arrival="2026-07-03", departure="2026-07-06", present=(), comments=None):
    comments = comments or {}
    return {
        "action": "checkin",
        "checkin_target": [target["token"]],
        f"checkin_state_{target['token']}": target["state_token"],
        f"arrival_date_{target['token']}": arrival,
        f"departure_date_{target['token']}": departure,
        f"attendance-submitted_{target['token']}": "1",
        f"attendance-present_{target['token']}": list(present),
        **{f"attendance-comment_{target['token']}_{day}": comment for day, comment in comments.items()},
    }


def _accepted_partner(owner, partner):
    return ParticipantBookingLink.objects.create(
        inviter=owner,
        invitee=partner,
        status=ParticipantBookingLink.Status.ACCEPTED,
    )


def _attendance_input(content, *, token, day):
    name = f"attendance-present_{token}"
    return next(
        tag for tag in re.findall(r"<input\b[^>]*>", content) if f'name="{name}"' in tag and f'value="{day}"' in tag
    )


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["kiosk-profile", "central-kiosk-profile"])
def test_profile_routes_require_a_valid_kiosk_identity(kiosk_client, route_name):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    participant = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=date(2026, 7, 6))

    response = kiosk_client.get(_profile_url(route_name, participant))

    assert response.status_code in {302, 401, 403}
    assert KIOSK_PARTICIPANT_SESSION_KEY not in kiosk_client.session


@pytest.mark.django_db
def test_primary_participant_can_update_only_identity_fields(kiosk_client):
    participant = ParticipantFactory(email="old@example.test", phone="000")
    _set_kiosk_identity(kiosk_client, participant=participant)

    response = kiosk_client.post(
        _profile_url("kiosk-profile", participant),
        {
            "first_name": "Ada Neu",
            "last_name": "Lovelace Neu",
            "email": "ada@example.test",
            "phone": "+49 111",
            "birth_date": "1990-01-02",
            "status": Participant.Status.CANCELLED,
            "hilfssatz": "1",
            "berufssatz": "1",
            "arrival_date": "2026-07-01",
            "departure_date": "2026-07-10",
            "notes": "forge",
        },
    )

    assert response.status_code in {200, 302}
    participant.refresh_from_db()
    assert (participant.first_name, participant.last_name) == ("Ada Neu", "Lovelace Neu")
    assert (participant.email, participant.phone) == ("ada@example.test", "+49 111")
    assert participant.status != Participant.Status.CANCELLED
    assert participant.notes != "forge"


@pytest.mark.django_db
def test_companion_pin_can_update_own_family_member_but_not_guardian(kiosk_client):
    guardian = ParticipantFactory(first_name="Guardian")
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Old",
        last_name="Companion",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    _set_kiosk_identity(kiosk_client, family_member=companion)

    response = kiosk_client.post(
        reverse("kiosk-family-member-profile", kwargs={"family_member_id": companion.pk}),
        {"first_name": "New", "last_name": "Companion", "guardian_first_name": "Forged"},
    )

    assert response.status_code in {200, 302}
    companion.refresh_from_db()
    guardian.refresh_from_db()
    assert companion.first_name == "New"
    assert guardian.first_name == "Guardian"


@pytest.mark.django_db
@pytest.mark.parametrize("target_kind", ["guardian", "child"])
def test_stale_companion_session_cannot_fall_back_to_guardian_profile_permissions(kiosk_client, target_kind):
    guardian = ParticipantFactory(first_name="Guardian")
    companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role=ParticipantFamilyMember.Role.COMPANION,
        is_active=True,
    )
    child = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role=ParticipantFamilyMember.Role.CHILD,
        first_name="Child",
        is_active=True,
    )
    _set_kiosk_identity(kiosk_client, family_member=companion)
    companion.is_active = False
    companion.save(update_fields=["is_active", "updated_at"])

    if target_kind == "guardian":
        url = _profile_url("kiosk-profile", guardian)
    else:
        url = reverse("kiosk-family-member-profile", kwargs={"family_member_id": child.pk})

    response = kiosk_client.post(url, {"first_name": "Forged", "last_name": "Identity"})

    guardian.refresh_from_db()
    child.refresh_from_db()
    assert response.status_code == 302
    assert response.headers["Location"].endswith(reverse("kiosk-login"))
    assert guardian.first_name == "Guardian"
    assert child.first_name == "Child"
    assert KIOSK_PARTICIPANT_SESSION_KEY not in kiosk_client.session
    assert KIOSK_FAMILY_MEMBER_SESSION_KEY not in kiosk_client.session


@pytest.mark.django_db
def test_guardian_can_edit_owned_child_but_not_partner_linked_participant(kiosk_client):
    guardian = ParticipantFactory()
    child = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Child",
        last_name="One",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    partner = ParticipantFactory(camp=guardian.camp)
    _accepted_partner(guardian, partner)
    _set_kiosk_identity(kiosk_client, participant=guardian)

    child_response = kiosk_client.post(
        reverse("kiosk-family-member-profile", kwargs={"family_member_id": child.pk}),
        {"first_name": "Child Updated", "last_name": "One"},
    )
    partner_response = kiosk_client.post(
        _profile_url("kiosk-profile", partner),
        {"first_name": "Partner Forged", "last_name": "One", "email": "x@example.test"},
    )

    assert child_response.status_code in {200, 302}
    assert partner_response.status_code in {302, 403, 404}
    child.refresh_from_db()
    partner.refresh_from_db()
    assert child.first_name == "Child Updated"
    assert partner.first_name != "Partner Forged"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"first_name": "", "last_name": "Valid"},
        {"first_name": "Future", "last_name": "DOB", "birth_date": "2999-01-01"},
        {"first_name": "Existing", "last_name": "Name"},
    ],
)
def test_invalid_profile_input_is_rejected_without_partial_write(kiosk_client, payload):
    participant = ParticipantFactory(first_name="Original", last_name="Person")
    ParticipantFactory(camp=participant.camp, first_name="Existing", last_name="Name")
    _set_kiosk_identity(kiosk_client, participant=participant)

    response = kiosk_client.post(_profile_url("kiosk-profile", participant), payload)

    assert response.status_code in {200, 400}
    participant.refresh_from_db()
    assert (participant.first_name, participant.last_name) == ("Original", "Person")


@pytest.mark.django_db
def test_admin_participant_detail_exposes_birth_date_derived_age_and_contact(client):
    participant = ParticipantFactory(email="ada@example.test", phone="+49 111")
    client.force_login(SuperUserFactory())

    response = client.get(reverse("participant-detail", kwargs={"participant_id": participant.pk}))

    assert response.status_code == 200
    content = response.content.decode()
    assert "birth_date" in content or "Geburtsdatum" in content
    assert "age" in content or "Alter" in content
    assert participant.email in content
    assert participant.phone in content


@pytest.mark.django_db
def test_checkin_calendar_uses_permitted_window_and_stay_ranges_exclusive(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    participant = ParticipantFactory(
        camp=camp,
        arrival_date=date(2026, 7, 3),
        departure_date=date(2026, 7, 6),
    )
    _set_kiosk_identity(kiosk_client, participant=participant)

    targets, response = _checkin_targets(kiosk_client)
    target = targets[f"participant-{participant.pk}"]
    content = response.content.decode()

    assert target["token"] in content
    for iso in ("2026-06-27", "2026-06-30", "2026-07-01", "2026-07-03", "2026-07-05", "2026-07-10", "2026-07-13"):
        field = _attendance_input(content, token=target["token"], day=iso)
        assert f'name="attendance-comment_{target["token"]}_{iso}"' not in content
        if iso in {"2026-07-03", "2026-07-04", "2026-07-05"}:
            assert "disabled" not in field
        else:
            assert "disabled" in field
    assert not re.search(
        rf'<input\b[^>]*name="attendance-present_{re.escape(target["token"])}"[^>]*value="2026-07-14"',
        content,
    )


@pytest.mark.django_db
def test_attendance_save_uses_checkin_action_and_persists_presence_and_comment(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    participant = ParticipantFactory(
        camp=camp,
        arrival_date=date(2026, 7, 3),
        departure_date=date(2026, 7, 6),
    )
    _set_kiosk_identity(kiosk_client, participant=participant)
    targets, _response = _checkin_targets(kiosk_client)
    target = targets[f"participant-{participant.pk}"]

    response = kiosk_client.post(
        reverse("kiosk-home"),
        _attendance_payload(
            target,
            present=["2026-07-03", "2026-07-05"],
            comments={"2026-07-03": "Needs a short operational note."},
        ),
    )

    assert response.status_code == 302
    assert list(
        AttendanceDay.objects.filter(participant=participant)
        .order_by("date")
        .values_list("date", "is_present", "comment")
    ) == [
        (date(2026, 7, 3), True, ""),
        (date(2026, 7, 4), False, ""),
        (date(2026, 7, 5), True, ""),
    ]


@pytest.mark.django_db
def test_partner_attendance_never_reads_or_overwrites_existing_comments(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    owner = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=date(2026, 7, 6))
    partner = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=date(2026, 7, 6))
    link = _accepted_partner(owner, partner)
    existing = AttendanceDay.objects.create(
        participant=owner,
        date=date(2026, 7, 3),
        is_present=False,
        comment="owner-only note",
    )
    _set_kiosk_identity(kiosk_client, participant=partner)
    targets, response = _checkin_targets(kiosk_client)
    target = targets[f"participant-{owner.pk}"]

    assert link.status == ParticipantBookingLink.Status.ACCEPTED
    assert "owner-only note" not in response.content.decode()
    save_response = kiosk_client.post(
        reverse("kiosk-home"),
        _attendance_payload(
            target,
            present=["2026-07-03"],
            comments={"2026-07-03": "partner secret"},
        ),
    )

    assert save_response.status_code == 302
    existing.refresh_from_db()
    assert existing.is_present is True
    assert existing.comment == "owner-only note"
    assert "partner secret" not in save_response.content.decode()


@pytest.mark.django_db
def test_kiosk_owner_cannot_read_or_overwrite_admin_only_attendance_comments(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    participant = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=date(2026, 7, 6))
    attendance = AttendanceDay.objects.create(
        participant=participant,
        date=date(2026, 7, 3),
        is_present=False,
        comment="admin-only operational note",
    )
    _set_kiosk_identity(kiosk_client, participant=participant)
    targets, response = _checkin_targets(kiosk_client)
    target = targets[f"participant-{participant.pk}"]

    content = response.content.decode()
    assert "admin-only operational note" not in content
    assert f"attendance-comment_{target['token']}" not in content

    save_response = kiosk_client.post(
        reverse("kiosk-home"),
        _attendance_payload(
            target,
            present=["2026-07-03"],
            comments={"2026-07-03": "forged kiosk comment"},
        ),
    )

    assert save_response.status_code == 302
    attendance.refresh_from_db()
    assert (attendance.is_present, attendance.comment) == (True, "admin-only operational note")


@pytest.mark.django_db
def test_child_without_own_dates_saves_attendance_for_the_guardian_stay(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    guardian = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=date(2026, 7, 6))
    child = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Kind",
        last_name="Ohne Reisedaten",
        role=ParticipantFamilyMember.Role.CHILD,
    )
    _set_kiosk_identity(kiosk_client, participant=guardian)
    targets, _response = _checkin_targets(kiosk_client)
    target = targets[f"family-{child.pk}"]

    response = kiosk_client.post(
        reverse("kiosk-home"),
        _attendance_payload(target, arrival="", departure="", present=["2026-07-03", "2026-07-05"]),
    )

    assert response.status_code == 302
    assert list(
        AttendanceDay.objects.filter(family_member=child).order_by("date").values_list("date", "is_present", "comment")
    ) == [
        (date(2026, 7, 3), True, ""),
        (date(2026, 7, 4), False, ""),
        (date(2026, 7, 5), True, ""),
    ]


@pytest.mark.django_db
def test_incomplete_attendance_target_does_not_block_another_valid_checkin_update(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    participant = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=date(2026, 7, 6))
    member = ParticipantFamilyMemberFactory(
        guardian=participant,
        arrival_date=date(2026, 7, 3),
        departure_date=date(2026, 7, 6),
    )
    _set_kiosk_identity(kiosk_client, participant=participant)
    targets, _response = _checkin_targets(kiosk_client)
    participant_target = targets[f"participant-{participant.pk}"]
    member_target = targets[f"family-{member.pk}"]

    response = kiosk_client.post(
        reverse("kiosk-home"),
        {
            **_attendance_payload(
                participant_target,
                arrival="2026-07-02",
                departure="2026-07-06",
                present=["2026-07-02"],
            ),
            "checkin_target": [participant_target["token"], member_target["token"]],
            f"checkin_state_{member_target['token']}": member_target["state_token"],
            f"arrival_date_{member_target['token']}": "",
            f"departure_date_{member_target['token']}": "",
            f"attendance-submitted_{member_target['token']}": "1",
            f"attendance-present_{member_target['token']}": ["2026-07-03"],
        },
    )

    assert response.status_code == 302
    participant.refresh_from_db()
    member.refresh_from_db()
    assert (participant.arrival_date, participant.departure_date) == (date(2026, 7, 2), date(2026, 7, 6))
    assert (member.arrival_date, member.departure_date) == (None, None)
    assert list(AttendanceDay.objects.filter(family_member=member)) == []


@pytest.mark.django_db
def test_checkin_audit_counts_only_the_exact_attendance_target(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    participant = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=date(2026, 7, 6))
    member = ParticipantFamilyMemberFactory(
        guardian=participant,
        arrival_date=date(2026, 7, 3),
        departure_date=date(2026, 7, 6),
    )
    AttendanceDay.objects.create(participant=participant, family_member=member, date=date(2026, 7, 3), is_present=True)
    _set_kiosk_identity(kiosk_client, participant=participant)
    targets, _response = _checkin_targets(kiosk_client)
    target = targets[f"participant-{participant.pk}"]

    response = kiosk_client.post(reverse("kiosk-home"), _attendance_payload(target, present=["2026-07-03"]))

    audit_log = KioskActionAuditLog.objects.get(action=KioskActionAuditLog.Action.CHECKIN_UPDATED)
    assert response.status_code == 302
    assert audit_log.before["attendance_present_nights"] == 0
    assert audit_log.after["attendance_present_nights"] == 1


@pytest.mark.django_db
def test_checkin_audit_snapshots_expose_only_allowed_attendance_metadata(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    participant = ParticipantFactory(
        camp=camp,
        arrival_date=date(2026, 7, 3),
        departure_date=date(2026, 7, 6),
        email="private-audit@example.test",
        phone="+49 999 417",
        birth_date=date(1990, 1, 2),
    )
    AttendanceDay.objects.create(
        participant=participant,
        date=date(2026, 7, 3),
        is_present=False,
        comment="secret attendance comment",
    )
    _set_kiosk_identity(kiosk_client, participant=participant)
    targets, _response = _checkin_targets(kiosk_client)
    target = targets[f"participant-{participant.pk}"]

    response = kiosk_client.post(reverse("kiosk-home"), _attendance_payload(target, present=["2026-07-03"]))

    audit_log = KioskActionAuditLog.objects.get(action=KioskActionAuditLog.Action.CHECKIN_UPDATED)
    allowed_keys = {
        "arrival_date",
        "departure_date",
        "booked_nights",
        "attendance_tracking_enabled",
        "attendance_present_nights",
    }
    assert response.status_code == 302
    assert set(audit_log.before) == allowed_keys
    assert set(audit_log.after) == allowed_keys
    snapshot = json.dumps({"before": audit_log.before, "after": audit_log.after})
    assert "secret attendance comment" not in snapshot
    assert "private-audit@example.test" not in snapshot
    assert "+49 999 417" not in snapshot
    assert "1990-01-02" not in snapshot


def _participant_detail_attendance_query_count(client, participant):
    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("participant-detail", kwargs={"participant_id": participant.pk}))

    assert response.status_code == 200
    return [query["sql"] for query in queries]


@pytest.mark.django_db
def test_admin_participant_detail_attendance_queries_are_constant_across_family_sizes(client):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 4))
    participants = []
    for family_size in (1, 4):
        participant = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 1), departure_date=date(2026, 7, 4))
        AttendanceDay.objects.create(participant=participant, date=date(2026, 7, 1), is_present=True)
        for _ in range(family_size):
            member = ParticipantFamilyMemberFactory(
                guardian=participant,
                arrival_date=date(2026, 7, 1),
                departure_date=date(2026, 7, 4),
            )
            AttendanceDay.objects.create(
                participant=participant,
                family_member=member,
                date=date(2026, 7, 1),
                is_present=True,
            )
        participants.append(participant)
    client.force_login(SuperUserFactory())

    one_member_queries = _participant_detail_attendance_query_count(client, participants[0])
    four_member_queries = _participant_detail_attendance_query_count(client, participants[1])
    one_member_attendance_queries = [query for query in one_member_queries if "billing_attendanceday" in query.lower()]
    four_member_attendance_queries = [
        query for query in four_member_queries if "billing_attendanceday" in query.lower()
    ]

    assert len(one_member_attendance_queries) == 2
    assert len(four_member_attendance_queries) == 2


@pytest.mark.django_db
def test_editor_participant_detail_does_not_query_attendance(client):
    participant = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=participant)
    AttendanceDay.objects.create(participant=participant, date=date(2026, 7, 3), is_present=True)
    AttendanceDay.objects.create(participant=participant, family_member=member, date=date(2026, 7, 3), is_present=True)
    editor = UserFactory(username="attendance-editor")
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    client.force_login(editor)

    queries = _participant_detail_attendance_query_count(client, participant)

    assert [query for query in queries if "billing_attendanceday" in query.lower()] == []


@pytest.mark.django_db
def test_partner_cannot_shorten_stay_and_delete_hidden_comment(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    owner = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=date(2026, 7, 6))
    partner = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=date(2026, 7, 6))
    _accepted_partner(owner, partner)
    protected = AttendanceDay.objects.create(
        participant=owner,
        date=date(2026, 7, 5),
        is_present=False,
        comment="owner-only note",
    )
    _set_kiosk_identity(kiosk_client, participant=partner)
    targets, _response = _checkin_targets(kiosk_client)
    target = targets[f"participant-{owner.pk}"]

    response = kiosk_client.post(
        reverse("kiosk-home"),
        _attendance_payload(target, departure="2026-07-05", present=["2026-07-03"]),
    )

    assert response.status_code == 200
    protected.refresh_from_db()
    assert protected.comment == "owner-only note"
    owner.refresh_from_db()
    assert owner.departure_date == date(2026, 7, 6)


@pytest.mark.django_db
def test_checkin_state_token_does_not_disclose_a_guessable_comment_hash():
    participant = ParticipantFactory()
    AttendanceDay.objects.create(participant=participant, date=date(2026, 7, 3), comment="private note")

    token = _sign_kiosk_checkin_state(participant, f"participant-{participant.pk}", participant)
    payload = signing.loads(token, salt="billing.kiosk-checkin-state.v1")

    assert sha256(b"private note").hexdigest() not in str(payload)


@pytest.mark.django_db
def test_checkin_state_token_expires_after_its_short_lifetime(monkeypatch):
    participant = ParticipantFactory()
    token = _sign_kiosk_checkin_state(participant, f"participant-{participant.pk}", participant)
    issued_at = signing.time.time()
    monkeypatch.setattr(signing.time, "time", lambda: issued_at + 16 * 60)

    assert _kiosk_checkin_original_state(token, participant, f"participant-{participant.pk}") is None


@pytest.mark.django_db
def test_prefetched_attendance_state_fingerprint_uses_no_per_target_query():
    participant = ParticipantFactory()
    AttendanceDay.objects.create(participant=participant, date=date(2026, 7, 3), comment="private note")
    target = Participant.objects.prefetch_related(
        Prefetch(
            "attendance_days",
            queryset=AttendanceDay.objects.order_by("date", "pk"),
            to_attr="prefetched_attendance_days",
        )
    ).get(pk=participant.pk)

    with CaptureQueriesContext(connection) as queries:
        fingerprint = _kiosk_attendance_fingerprint(target)

    assert fingerprint
    assert len(queries) == 0


@pytest.mark.django_db
def test_participant_attendance_fingerprint_ignores_family_member_rows_without_prefetch():
    participant = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=participant)
    family_attendance = AttendanceDay.objects.create(
        participant=participant,
        family_member=member,
        date=date(2026, 7, 3),
        comment="first family state",
    )

    original = _kiosk_attendance_fingerprint(participant)
    family_attendance.comment = "changed family state"
    family_attendance.save(update_fields=["comment", "updated_at"])

    assert _kiosk_attendance_fingerprint(participant) == original


@pytest.mark.django_db
def test_own_guardian_and_admin_can_read_daily_comments_and_totals(client, kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    participant = ParticipantFactory()
    _set_kiosk_identity(kiosk_client, participant=participant)
    kiosk_client.get(reverse("kiosk-home"))
    client.force_login(SuperUserFactory())

    detail = client.get(reverse("participant-detail", kwargs={"participant_id": participant.pk}))
    overview = client.get(reverse("camp-attendance-overview", kwargs={"camp_id": participant.camp.pk}))

    assert detail.status_code == 200
    assert overview.status_code == 200
    assert "attendance_totals" in overview.context
    assert "daily_comments" in overview.context


@pytest.mark.django_db
def test_stale_checkin_state_token_rejects_update_after_attendance_mutation(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    participant = ParticipantFactory(
        camp=camp,
        arrival_date=date(2026, 7, 3),
        departure_date=date(2026, 7, 6),
    )
    _set_kiosk_identity(kiosk_client, participant=participant)
    targets, _response = _checkin_targets(kiosk_client)
    target = targets[f"participant-{participant.pk}"]
    attendance = AttendanceDay.objects.create(
        participant=participant,
        date=date(2026, 7, 3),
        is_present=False,
        comment="original",
    )
    AttendanceDay.objects.filter(pk=attendance.pk).update(is_present=True)

    response = kiosk_client.post(
        reverse("kiosk-home"),
        _attendance_payload(target, present=["2026-07-03"], comments={"2026-07-03": "overwrite"}),
    )

    assert response.status_code == 200
    attendance.refresh_from_db()
    assert (attendance.is_present, attendance.comment) == (True, "original")


@pytest.mark.django_db
def test_profile_and_attendance_mutations_create_safe_audit_entries(kiosk_client, monkeypatch):
    monkeypatch.setattr("billing.models.timezone.localdate", lambda: date(2026, 7, 5))
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 10))
    participant = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=date(2026, 7, 6))
    _set_kiosk_identity(kiosk_client, participant=participant)
    kiosk_client.post(
        _profile_url("kiosk-profile", participant),
        {"first_name": "Changed", "last_name": participant.last_name, "email": participant.email},
    )
    targets, _response = _checkin_targets(kiosk_client)
    target = targets[f"participant-{participant.pk}"]
    kiosk_client.post(
        reverse("kiosk-home"),
        _attendance_payload(target, present=["2026-07-03"], comments={"2026-07-03": "safe"}),
    )

    entries = KioskActionAuditLog.objects.filter(target_participant=participant)
    assert entries.count() >= 2
    assert all("safe" not in entry.description for entry in entries)
    assert all("password" not in entry.description.lower() for entry in entries)
    attendance_entry = entries.get(action=KioskActionAuditLog.Action.CHECKIN_UPDATED)
    assert "attendance" not in attendance_entry.before
    assert "attendance" not in attendance_entry.after
    assert attendance_entry.after["attendance_present_nights"] == 1


@pytest.mark.django_db
def test_editor_cannot_see_profile_pii_on_participant_detail(client):
    participant = ParticipantFactory(
        email="private-contact@example.test",
        phone="+49 999 417",
        birth_date=date(1990, 1, 2),
    )
    editor = UserFactory(username="pii-editor")
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    client.force_login(editor)

    response = client.get(reverse("participant-detail", args=[participant.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "private-contact@example.test" not in content
    assert "+49 999 417" not in content
    assert "02.01.1990" not in content
    assert "Stammdaten" not in content
