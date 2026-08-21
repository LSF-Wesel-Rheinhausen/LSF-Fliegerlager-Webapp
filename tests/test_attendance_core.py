from datetime import date
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from billing.attendance import (
    attendance_window,
    build_target_attendance_calendar,
    iter_overnight_dates,
    prepare_attendance_replacement_payload,
)
from billing.attendance_views import camp_attendance_overview
from billing.models import AttendanceDay
from tests.factories import CampFactory, ParticipantFactory, ParticipantFamilyMemberFactory, SuperUserFactory


def test_iter_overnight_dates_includes_arrival_and_excludes_departure():
    assert list(iter_overnight_dates(date(2026, 7, 3), date(2026, 7, 6))) == [
        date(2026, 7, 3),
        date(2026, 7, 4),
        date(2026, 7, 5),
    ]


@pytest.mark.django_db
def test_attendance_window_includes_setup_and_departure_days_and_requires_both_bounds():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 5))

    assert attendance_window(camp) == (date(2026, 6, 27), date(2026, 7, 9))
    camp.ends_on = None
    assert attendance_window(camp) is None


@pytest.mark.django_db
def test_calendar_covers_attendance_window_marks_stay_and_exposes_authorized_comments():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 5))
    participant = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 2), departure_date=date(2026, 7, 4))
    AttendanceDay.objects.create(
        participant=participant, date=date(2026, 7, 2), is_present=False, comment="Private note"
    )

    calendar = build_target_attendance_calendar(participant, camp, include_comments=False)

    assert [(entry["date"], entry["disabled"], entry["is_present"], entry["comment"]) for entry in calendar] == [
        (date(2026, 6, 27), True, False, None),
        (date(2026, 6, 28), True, False, None),
        (date(2026, 6, 29), True, False, None),
        (date(2026, 6, 30), True, False, None),
        (date(2026, 7, 1), True, False, None),
        (date(2026, 7, 2), False, False, None),
        (date(2026, 7, 3), False, True, None),
        (date(2026, 7, 4), True, False, None),
        (date(2026, 7, 5), True, False, None),
        (date(2026, 7, 6), True, False, None),
        (date(2026, 7, 7), True, False, None),
        (date(2026, 7, 8), True, False, None),
    ]
    assert build_target_attendance_calendar(participant, camp, include_comments=True)[5]["comment"] == "Private note"


@pytest.mark.django_db
def test_calendar_treats_missing_tracked_stay_days_as_absent():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 5))
    participant = ParticipantFactory(
        camp=camp,
        arrival_date=date(2026, 7, 2),
        departure_date=date(2026, 7, 4),
        attendance_tracking_enabled=True,
    )

    calendar = build_target_attendance_calendar(participant, camp, include_comments=False)

    assert [(entry["date"], entry["status"], entry["is_present"]) for entry in calendar[5:7]] == [
        (date(2026, 7, 2), "absent", False),
        (date(2026, 7, 3), "absent", False),
    ]


@pytest.mark.django_db
def test_participant_calendar_ignores_family_member_attendance_rows():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 5))
    participant = ParticipantFactory(
        camp=camp,
        arrival_date=date(2026, 7, 2),
        departure_date=date(2026, 7, 4),
        attendance_tracking_enabled=True,
    )
    member = ParticipantFamilyMemberFactory(guardian=participant)
    AttendanceDay.objects.create(
        participant=participant,
        date=date(2026, 7, 2),
        is_present=False,
        comment="Participant note",
    )
    AttendanceDay.objects.create(
        participant=participant,
        family_member=member,
        date=date(2026, 7, 2),
        is_present=True,
        comment="Family note",
    )

    entry = next(
        day
        for day in build_target_attendance_calendar(participant, camp, include_comments=True)
        if day["date"] == date(2026, 7, 2)
    )

    assert entry["is_present"] is False
    assert entry["comment"] == "Participant note"


@pytest.mark.django_db
def test_prepare_payload_accepts_existing_field_names_and_preserves_hidden_comments():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 5))
    participant = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 2), departure_date=date(2026, 7, 4))
    AttendanceDay.objects.create(participant=participant, date=date(2026, 7, 2), is_present=False, comment="Owner note")

    prepared = prepare_attendance_replacement_payload(
        {
            "attendance-present_participant-1": ["2026-07-02"],
            "attendance-comment_participant-1_2026-07-02": "Partner overwrite",
        },
        target=participant,
        camp=camp,
        token="participant-1",
        include_comments=False,
    )

    assert (prepared.start_date, prepared.end_date) == (date(2026, 7, 2), date(2026, 7, 4))
    assert prepared.days == [
        {"date": date(2026, 7, 2), "is_present": True},
        {"date": date(2026, 7, 3), "is_present": False},
    ]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"attendance-present_participant-1": ["not-a-date"]},
        {"attendance-present_participant-1": ["2026-07-04"]},
        {"attendance-comment_participant-1_2026-07-02": "x" * 501},
    ],
)
def test_prepare_payload_rejects_invalid_out_of_range_and_oversized_values(payload):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 5))
    participant = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 2), departure_date=date(2026, 7, 4))

    with pytest.raises(ValidationError):
        prepare_attendance_replacement_payload(
            payload, target=participant, camp=camp, token="participant-1", include_comments=True
        )


@pytest.mark.django_db
def test_admin_overview_is_camp_scoped_and_includes_people_totals_and_comments():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 3))
    participant = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 1), departure_date=date(2026, 7, 3))
    member = ParticipantFamilyMemberFactory(
        guardian=participant, arrival_date=date(2026, 7, 1), departure_date=date(2026, 7, 3)
    )
    AttendanceDay.objects.create(participant=participant, date=date(2026, 7, 1), is_present=True, comment="Arrived")
    AttendanceDay.objects.create(participant=participant, family_member=member, date=date(2026, 7, 1), is_present=False)
    other_camp = CampFactory(name="Anderes Lager", year=2027, starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 3))
    other = ParticipantFactory(camp=other_camp, arrival_date=date(2026, 7, 1), departure_date=date(2026, 7, 3))
    AttendanceDay.objects.create(participant=other, date=date(2026, 7, 1), is_present=True, comment="Leak")
    request = RequestFactory().get("/camps/attendance/")
    request.user = SuperUserFactory()

    with patch("billing.attendance_views.render") as render:
        camp_attendance_overview(request, camp.pk)

    _request, template_name, context = render.call_args.args
    assert template_name == "billing/camp_attendance_overview.html"
    assert context["attendance_totals"] == [
        {
            "date": attendance_date,
            "present": 1 if attendance_date == date(2026, 7, 1) else 2 if attendance_date == date(2026, 7, 2) else 0,
            "absent": 1 if attendance_date == date(2026, 7, 1) else 0,
        }
        for attendance_date in iter_overnight_dates(date(2026, 6, 27), date(2026, 7, 7))
    ]
    assert context["daily_comments"] == [
        {"date": date(2026, 7, 1), "person": participant.full_name, "comment": "Arrived"}
    ]
    assert [person["name"] for person in context["attendance_people"]] == [participant.full_name, member.full_name]


@pytest.mark.django_db
def test_admin_overview_includes_zero_totals_for_every_date_of_an_empty_camp():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 3))
    request = RequestFactory().get("/camps/attendance/")
    request.user = SuperUserFactory()

    with patch("billing.attendance_views.render") as render:
        camp_attendance_overview(request, camp.pk)

    context = render.call_args.args[2]
    assert context["attendance_totals"] == [
        {"date": attendance_date, "present": 0, "absent": 0}
        for attendance_date in iter_overnight_dates(date(2026, 6, 27), date(2026, 7, 7))
    ]
