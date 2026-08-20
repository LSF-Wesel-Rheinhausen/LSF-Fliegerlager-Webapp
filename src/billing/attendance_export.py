"""Create the administrator attendance workbook for one camp."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .attendance import attendance_window, iter_overnight_dates, target_stay_for
from .models import AttendanceDay, Participant, ParticipantFamilyMember

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_ACTIVE_PARTICIPANT_STATUSES = (
    Participant.Status.REGISTERED,
    Participant.Status.ACTIVE,
    Participant.Status.SETTLED,
)


def _safe_cell_value(value: Any) -> Any:
    """Return a value that cannot be interpreted as a spreadsheet formula."""
    if isinstance(value, str) and value.lstrip().startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _camp_dates(camp: Any) -> list[date]:
    window = attendance_window(camp)
    if window is None:
        return []
    return list(iter_overnight_dates(*window))


def _age_on(person: Any, reference_date: date) -> int | None:
    try:
        return person.age_on(reference_date)
    except ValidationError:
        return None


def _in_range(person: Any, camp: Any, day: date) -> bool:
    stay = target_stay_for(person, camp)
    return stay is not None and stay[0] <= day < stay[1]


def _status(
    person: Any,
    camp: Any,
    day: date,
    attendance_by_person: dict[tuple[str, int], dict[date, AttendanceDay]],
) -> str:
    if not _in_range(person, camp, day):
        return "Außerhalb"
    if not person.attendance_tracking_enabled:
        return "Anwesend"
    key = ("family" if isinstance(person, ParticipantFamilyMember) else "participant", person.pk)
    attendance = attendance_by_person.get(key, {}).get(day)
    return "Anwesend" if attendance is not None and attendance.is_present else "Abwesend"


def _style_sheet(sheet: Any, widths: dict[int, float]) -> None:
    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for column, width in widths.items():
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.freeze_panes = "C2" if sheet.title == "Anwesenheit" else "A2"
    sheet.auto_filter.ref = sheet.dimensions


def attendance_workbook_response(camp: Any) -> HttpResponse:
    """Build an XLSX download containing attendance matrix and daily totals.

    Parameters:
        camp: Camp-like object with ``year``, ``starts_on`` and ``ends_on``.

    Returns:
        An attachment response named ``anwesenheit-<year>.xlsx``.
    """
    days = _camp_dates(camp)
    workbook = Workbook()
    workbook.iso_dates = True
    attendance_sheet = workbook.active
    attendance_sheet.title = "Anwesenheit"
    summary_sheet = workbook.create_sheet("Tagesübersicht")

    attendance_sheet.append(["Name", "Alter", *days])
    summary_sheet.append(["Datum", "Anwesend", "Abwesend", "Kommentare"])

    if days:
        participants = list(
            Participant.objects.filter(
                camp=camp,
                archived_at__isnull=True,
                status__in=_ACTIVE_PARTICIPANT_STATUSES,
            ).prefetch_related("family_members")
        )
        people: list[Participant | ParticipantFamilyMember] = list(participants)
        for participant in participants:
            people.extend(member for member in participant.family_members.all() if member.is_active)
        people.sort(key=lambda person: (person.last_name.casefold(), person.first_name.casefold(), person.pk))

        attendance_records = list(
            AttendanceDay.objects.filter(participant__camp=camp).select_related("family_member").order_by("date", "pk")
        )
        attendance_by_person: dict[tuple[str, int], dict[date, AttendanceDay]] = {}
        for attendance in attendance_records:
            key = (
                "family" if attendance.family_member_id is not None else "participant",
                attendance.family_member_id or attendance.participant_id,
            )
            attendance_by_person.setdefault(key, {})[attendance.date] = attendance

        for person in people:
            attendance_sheet.append(
                [
                    _safe_cell_value(person.full_name),
                    _age_on(person, camp.starts_on),
                    *[_status(person, camp, day, attendance_by_person) for day in days],
                ]
            )

        for day in days:
            statuses = [_status(person, camp, day, attendance_by_person) for person in people]
            comments: list[str] = []
            people_by_key = {
                ("family" if isinstance(person, ParticipantFamilyMember) else "participant", person.pk): person
                for person in people
            }
            for attendance in attendance_records:
                if attendance.date != day or not attendance.comment:
                    continue
                key = (
                    "family" if attendance.family_member_id is not None else "participant",
                    attendance.family_member_id or attendance.participant_id,
                )
                target_person = people_by_key.get(key)
                if target_person is not None and _in_range(target_person, camp, day):
                    comments.append(_safe_cell_value(attendance.comment))
            summary_sheet.append(
                [
                    day,
                    statuses.count("Anwesend"),
                    statuses.count("Abwesend"),
                    "; ".join(comments),
                ]
            )

    for column in range(3, attendance_sheet.max_column + 1):
        attendance_sheet.cell(1, column).number_format = "DD.MM.YYYY"
    for row in range(2, summary_sheet.max_row + 1):
        summary_sheet.cell(row, 1).number_format = "DD.MM.YYYY"

    _style_sheet(
        attendance_sheet,
        {1: 30, 2: 10, **{column: 14 for column in range(3, attendance_sheet.max_column + 1)}},
    )
    _style_sheet(summary_sheet, {1: 14, 2: 12, 3: 12, 4: 60})

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(output.getvalue(), content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="anwesenheit-{camp.year}.xlsx"'
    return response
