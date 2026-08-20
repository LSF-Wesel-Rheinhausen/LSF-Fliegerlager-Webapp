"""Presentation-safe attendance contracts shared by kiosk and admin views."""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date

from .models import AttendanceDay, Camp, Participant, ParticipantFamilyMember

AttendanceTarget = Participant | ParticipantFamilyMember


@dataclass(frozen=True)
class AttendanceReplacementPayload:
    """Validated input suitable for ``replace_attendance_days``.

    Comment keys are omitted when the caller lacks comment access.  The
    replacement service consequently preserves an existing comment, preventing
    partner updates from overwriting hidden data.
    """

    start_date: date
    end_date: date
    days: list[dict[str, date | bool | str | None]]


def iter_overnight_dates(start: date, end: date) -> Iterator[date]:
    """Yield the arrival-inclusive, departure-exclusive dates in a stay."""
    current = start
    while current < end:
        yield current
        current += timedelta(days=1)


def attendance_window(camp: Camp) -> tuple[date, date] | None:
    """Return the permitted setup-to-departure attendance window for a camp.

    The window starts four days before camp start (inclusive) and ends four
    days after camp end (exclusive).  Incomplete or invalid camp dates produce
    no deterministic attendance window instead of inventing a bound.
    """
    if camp.starts_on is None or camp.ends_on is None or camp.starts_on >= camp.ends_on:
        return None
    return camp.starts_on - timedelta(days=4), camp.ends_on + timedelta(days=4)


def build_target_attendance_calendar(
    target: AttendanceTarget,
    camp: Camp,
    *,
    include_comments: bool,
) -> list[dict[str, date | bool | str | None]]:
    """Build the complete camp calendar for one attendance target.

    Dates outside the target stay are disabled. Missing in-stay records use
    the legacy-present fallback only while tracking is disabled.
    Comments are returned only for authorized callers.
    """
    _validate_target_camp(target, camp)
    window = attendance_window(camp)
    if window is None:
        return []

    attendance_by_date = {record.date: record for record in _target_attendance_records(target)}
    target_stay = target_stay_for(target, camp)
    calendar: list[dict[str, date | bool | str | None]] = []
    for attendance_date in iter_overnight_dates(*window):
        enabled = target_stay is not None and target_stay[0] <= attendance_date < target_stay[1]
        record = attendance_by_date.get(attendance_date)
        is_present = enabled and (record.is_present if record is not None else not target.attendance_tracking_enabled)
        status = "disabled" if not enabled else ("present" if is_present else "absent")
        calendar.append(
            {
                "date": attendance_date,
                "disabled": not enabled,
                "status": status,
                "is_present": is_present,
                "comment": record.comment if include_comments and record is not None else None,
            }
        )
    return calendar


def prepare_attendance_replacement_payload(
    payload: Mapping[str, Any],
    *,
    target: AttendanceTarget,
    camp: Camp,
    token: str,
    include_comments: bool,
    arrival_date: date | None = None,
    departure_date: date | None = None,
    use_submitted_stay: bool = False,
) -> AttendanceReplacementPayload:
    """Parse existing check-in fields into the attendance service contract.

    Accepted field names are ``attendance-present_<token>`` (a date list) and
    ``attendance-comment_<token>_<iso-date>``.  Values must fall within the
    target's stay and comments are limited to the model's 500 characters.
    """
    _validate_target_camp(target, camp)
    target_stay = target_stay_for(
        target,
        camp,
        arrival_date=arrival_date,
        departure_date=departure_date,
        use_submitted_stay=use_submitted_stay,
    )
    if target_stay is None:
        raise ValidationError("Der Anwesenheitsbereich muss mindestens eine Nacht enthalten.")
    start_date, end_date = target_stay

    present_dates = _parse_present_dates(payload, token, start_date, end_date)
    comments = _parse_comments(payload, token, start_date, end_date) if include_comments else {}
    days = []
    for attendance_date in iter_overnight_dates(start_date, end_date):
        day: dict[str, date | bool | str | None] = {
            "date": attendance_date,
            "is_present": attendance_date in present_dates,
        }
        if include_comments:
            day["comment"] = comments.get(attendance_date, "")
        days.append(day)
    return AttendanceReplacementPayload(start_date=start_date, end_date=end_date, days=days)


def _target_attendance_records(target: AttendanceTarget) -> Sequence[AttendanceDay]:
    records = getattr(target, "prefetched_attendance_days", None)
    if records is not None:
        return records
    return list(target.attendance_days.all())


def target_stay_for(
    target: AttendanceTarget,
    camp: Camp,
    *,
    arrival_date: date | None = None,
    departure_date: date | None = None,
    use_submitted_stay: bool = False,
) -> tuple[date, date] | None:
    window = attendance_window(camp)
    if window is None:
        return None
    if isinstance(target, ParticipantFamilyMember):
        if use_submitted_stay:
            arrival = arrival_date or target.guardian.arrival_date
            departure = departure_date or target.guardian.departure_date
        else:
            arrival = target.arrival_date or target.guardian.arrival_date
            departure = target.departure_date or target.guardian.departure_date
    else:
        arrival = arrival_date if use_submitted_stay else target.arrival_date
        departure = departure_date if use_submitted_stay else target.departure_date
    if arrival is None or departure is None:
        return None
    start_date, end_date = max(arrival, window[0]), min(departure, window[1])
    return (start_date, end_date) if start_date < end_date else None


def _validate_target_camp(target: AttendanceTarget, camp: Camp) -> None:
    target_camp_id = target.guardian.camp_id if isinstance(target, ParticipantFamilyMember) else target.camp_id
    if target_camp_id != camp.pk:
        raise ValidationError("Anwesenheit darf nur für das zugehörige Lager verarbeitet werden.")


def _parse_present_dates(payload: Mapping[str, Any], token: str, start_date: date, end_date: date) -> set[date]:
    field_name = f"attendance-present_{token}"
    values = payload.getlist(field_name) if hasattr(payload, "getlist") else payload.get(field_name, [])
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, Sequence):
        raise ValidationError("Anwesenheit muss als Datums-Liste angegeben werden.")
    return {_parse_permitted_date(value, start_date, end_date) for value in values}


def _parse_comments(payload: Mapping[str, Any], token: str, start_date: date, end_date: date) -> dict[date, str]:
    prefix = f"attendance-comment_{token}_"
    comments: dict[date, str] = {}
    for field_name, value in payload.items():
        if not field_name.startswith(prefix):
            continue
        attendance_date = _parse_permitted_date(field_name.removeprefix(prefix), start_date, end_date)
        if not isinstance(value, str) or len(value) > 500:
            raise ValidationError("Der Kommentar darf höchstens 500 Zeichen enthalten.")
        comments[attendance_date] = value
    return comments


def _parse_permitted_date(value: Any, start_date: date, end_date: date) -> date:
    if not isinstance(value, str):
        raise ValidationError("Anwesenheit benötigt ein gültiges ISO-Datum.")
    parsed = parse_date(value)
    if parsed is None or value != parsed.isoformat():
        raise ValidationError("Anwesenheit benötigt ein gültiges ISO-Datum.")
    if parsed < start_date or parsed >= end_date:
        raise ValidationError("Der Anwesenheitstag liegt außerhalb des Aufenthaltsbereichs.")
    return parsed
