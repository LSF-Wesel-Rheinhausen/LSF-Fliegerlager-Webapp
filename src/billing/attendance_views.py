"""Isolated administrative attendance presentation view for later URL wiring."""

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render

from .attendance import attendance_window, build_target_attendance_calendar, iter_overnight_dates
from .attendance_export import attendance_workbook_response
from .models import AttendanceDay, Camp, Participant, ParticipantFamilyMember
from .permissions import admin_required

_ACTIVE_PARTICIPANT_STATUSES = (
    Participant.Status.REGISTERED,
    Participant.Status.ACTIVE,
    Participant.Status.SETTLED,
)


@admin_required
def camp_attendance_overview(request, camp_id: int):
    """Render the camp-scoped attendance overview for administrative users only."""
    camp = get_object_or_404(Camp, pk=camp_id)
    attendance = AttendanceDay.objects.filter(participant__camp=camp).order_by("date", "pk")
    members = ParticipantFamilyMember.objects.prefetch_related(
        Prefetch(
            "attendance_days",
            queryset=attendance.filter(family_member__isnull=False),
            to_attr="prefetched_attendance_days",
        )
    )
    participants = (
        Participant.objects.filter(
            camp=camp,
            archived_at__isnull=True,
            status__in=_ACTIVE_PARTICIPANT_STATUSES,
        )
        .prefetch_related(
            Prefetch(
                "attendance_days",
                queryset=attendance.filter(family_member__isnull=True),
                to_attr="prefetched_attendance_days",
            ),
            Prefetch("family_members", queryset=members.filter(is_active=True)),
        )
        .order_by("last_name", "first_name", "pk")
    )

    people = []
    for participant in participants:
        people.append(_attendance_person(participant, camp))
        people.extend(_attendance_person(member, camp) for member in participant.family_members.all())

    totals: dict[object, dict[str, object]] = {
        attendance_date: {"date": attendance_date, "present": 0, "absent": 0} for attendance_date in _camp_dates(camp)
    }
    comments = []
    for person in people:
        for entry in person["calendar"]:
            if entry["disabled"]:
                continue
            total = totals[entry["date"]]
            count_key = "present" if entry["is_present"] else "absent"
            current_count = total[count_key]
            if not isinstance(current_count, int):
                raise RuntimeError("Anwesenheitssummen müssen ganze Zahlen sein.")
            total[count_key] = current_count + 1
            if entry["comment"]:
                comments.append({"date": entry["date"], "person": person["name"], "comment": entry["comment"]})

    attendance_totals = list(totals.values())
    return render(
        request,
        "billing/camp_attendance_overview.html",
        {
            "camp": camp,
            "attendance_people": people,
            "attendance_totals": attendance_totals,
            "daily_comments": comments,
            "admin_only": True,
        },
    )


@admin_required
def attendance_workbook(request, camp_id: int):
    """Download the attendance workbook for one camp for administrators only."""
    camp = get_object_or_404(Camp, pk=camp_id)
    return attendance_workbook_response(camp)


def _attendance_person(target, camp):
    return {
        "name": target.full_name,
        "target": target,
        "calendar": build_target_attendance_calendar(target, camp, include_comments=True),
    }


def _camp_dates(camp):
    window = attendance_window(camp)
    if window is None:
        return []
    return iter_overnight_dates(*window)
