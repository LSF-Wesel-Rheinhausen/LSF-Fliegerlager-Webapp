from datetime import date, timedelta
from io import BytesIO

import pytest
from django.urls import reverse
from openpyxl import load_workbook

from billing.attendance_export import attendance_workbook_response
from billing.models import AttendanceDay, Participant, ParticipantFamilyMember
from billing.permissions import EDITOR_GROUP
from tests.factories import (
    CampFactory,
    GroupFactory,
    ParticipantFactory,
    ParticipantFamilyMemberFactory,
    SuperUserFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
UNSAFE_FORMULA_PREFIXES = ("=", "+", "-", "@")


def create_attendance(*, person, day, status, comment=""):
    fields = {"date": day, "is_present": status == "present", "comment": comment}
    if isinstance(person, ParticipantFamilyMember):
        fields["participant"] = person.guardian
        fields["family_member"] = person
    else:
        fields["participant"] = person
    return AttendanceDay.objects.create(**fields)


@pytest.fixture
def attendance_dataset():
    camp = CampFactory(
        year=2026,
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 5),
    )
    other_camp = CampFactory(
        year=2027,
        starts_on=date(2027, 7, 1),
        ends_on=date(2027, 7, 3),
    )
    participant = ParticipantFactory(
        camp=camp,
        first_name="=SUM(1,1)",
        last_name="Lovelace",
        email="private@example.test",
        phone="+49123456789",
        notes="private participant note",
        arrival_date=date(2026, 7, 2),
        departure_date=date(2026, 7, 4),
    )
    participant.birth_date = date(2010, 6, 30)
    participant.save()
    family_member = ParticipantFamilyMemberFactory(
        guardian=participant,
        first_name="Ada",
        last_name="=Family",
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 5),
    )
    family_member.birth_date = date(2015, 7, 2)
    family_member.save()
    legacy_participant = ParticipantFactory(
        camp=camp,
        first_name="Legacy",
        last_name="Dates",
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 3),
        attendance_tracking_enabled=False,
    )
    legacy_participant.birth_date = date(2012, 6, 30)
    legacy_participant.save()
    create_attendance(
        person=participant,
        day=date(2026, 7, 2),
        status="present",
        comment='+HYPERLINK("https://example.test")',
    )
    create_attendance(person=participant, day=date(2026, 7, 3), status="absent", comment="Krank")
    participant.attendance_tracking_enabled = True
    participant.save(update_fields=["attendance_tracking_enabled", "updated_at"])
    create_attendance(person=family_member, day=date(2026, 7, 2), status="absent", comment="Familiennotiz")
    family_member.attendance_tracking_enabled = True
    family_member.save(update_fields=["attendance_tracking_enabled", "updated_at"])
    ParticipantFactory(camp=other_camp, first_name="Other", last_name="Camp")

    archived = ParticipantFactory(
        camp=camp,
        first_name="Archived",
        last_name="Person",
        archived_at="2026-06-01T00:00:00Z",
    )
    cancelled = ParticipantFactory(
        camp=camp,
        first_name="Cancelled",
        last_name="Person",
        status=Participant.Status.CANCELLED,
    )
    inactive_guardian = ParticipantFactory(camp=camp, first_name="Inactive", last_name="Guardian")
    inactive_family_member = ParticipantFamilyMemberFactory(
        guardian=inactive_guardian,
        first_name="Inactive",
        last_name="Family",
        is_active=False,
    )
    return camp, participant, family_member, legacy_participant, archived, cancelled, inactive_family_member


def test_attendance_workbook_response_core_returns_workbook(attendance_dataset):
    camp, *_ = attendance_dataset

    response = attendance_workbook_response(camp)

    assert response["Content-Type"] == XLSX_CONTENT_TYPE
    assert response["Content-Disposition"] == 'attachment; filename="anwesenheit-2026.xlsx"'
    workbook = load_workbook(BytesIO(response.content), data_only=False)
    assert workbook.sheetnames == ["Anwesenheit", "Tagesübersicht"]


def test_attendance_workbook_requires_admin_and_allows_admin(client, attendance_dataset):
    camp, *_ = attendance_dataset
    url = reverse("attendance-workbook", args=[camp.pk])

    assert client.get(url).status_code == 302

    editor = UserFactory(username="editor")
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    client.force_login(editor)
    assert client.get(url).status_code == 302

    client.force_login(UserFactory(username="ordinary"))
    assert client.get(url).status_code == 302

    client.force_login(SuperUserFactory(username="admin"))
    assert client.get(url).status_code == 200


def test_attendance_workbook_response_has_xlsx_mime_and_year_filename(client, attendance_dataset):
    camp, *_ = attendance_dataset

    response = attendance_workbook_response(camp)

    assert response["Content-Type"] == XLSX_CONTENT_TYPE
    assert response["Content-Disposition"] == 'attachment; filename="anwesenheit-2026.xlsx"'


def test_attendance_sheet_contains_sorted_matrix_and_typed_dates(client, attendance_dataset):
    (
        camp,
        participant,
        family_member,
        legacy_participant,
        archived,
        cancelled,
        inactive_family_member,
    ) = attendance_dataset
    workbook = load_workbook(
        BytesIO(attendance_workbook_response(camp).content),
        data_only=False,
    )
    sheet = workbook["Anwesenheit"]

    expected_days = [date(2026, 6, 27) + timedelta(days=offset) for offset in range(12)]
    assert [cell.value for cell in sheet[1]] == ["Name", "Alter", *expected_days]
    assert all(isinstance(sheet.cell(1, column).value, date) for column in range(3, 15))
    assert all(sheet.cell(1, column).number_format != "General" for column in range(3, 15))
    assert [sheet.cell(row, 1).value for row in range(2, sheet.max_row + 1)] == [
        family_member.full_name,
        legacy_participant.full_name,
        "Inactive Guardian",
        "'" + participant.full_name,
    ]
    assert [sheet.cell(row, 2).value for row in range(2, 6)] == [10, 14, None, 16]
    assert [sheet.cell(2, column).value for column in range(3, 15)] == [
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Abwesend",
        "Abwesend",
        "Abwesend",
        "Abwesend",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
    ]
    assert [sheet.cell(3, column).value for column in range(3, 15)] == [
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Anwesend",
        "Anwesend",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
    ]
    assert [sheet.cell(4, column).value for column in range(3, 15)] == [
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
    ]
    assert [sheet.cell(5, column).value for column in range(3, 15)] == [
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Anwesend",
        "Abwesend",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
        "Außerhalb",
    ]
    exported_text = "\n".join(str(cell.value) for row in sheet.iter_rows() for cell in row if cell.value is not None)
    assert archived.full_name not in exported_text
    assert cancelled.full_name not in exported_text
    assert inactive_family_member.full_name not in exported_text
    assert "private@example.test" not in exported_text
    assert "+49123456789" not in exported_text
    assert "private participant note" not in exported_text
    assert "Krank" not in exported_text


def test_attendance_summary_has_present_absent_totals_and_visible_comments(client, attendance_dataset):
    camp, *_ = attendance_dataset

    workbook = load_workbook(BytesIO(attendance_workbook_response(camp).content))
    sheet = workbook["Tagesübersicht"]

    assert [cell.value for cell in sheet[1]] == ["Datum", "Anwesend", "Abwesend", "Kommentare"]
    assert [sheet.cell(row, 1).value for row in range(2, 14)] == [
        date(2026, 6, 27) + timedelta(days=offset) for offset in range(12)
    ]
    assert [sheet.cell(row, 2).value for row in range(2, 14)] == [0, 0, 0, 0, 1, 2, 0, 0, 0, 0, 0, 0]
    assert [sheet.cell(row, 3).value for row in range(2, 14)] == [0, 0, 0, 0, 1, 1, 2, 1, 0, 0, 0, 0]
    assert sheet.cell(7, 4).value == '\'+HYPERLINK("https://example.test"); Familiennotiz'
    assert sheet.cell(8, 4).value == "Krank"
    assert isinstance(sheet.cell(2, 1).value, date)


def test_attendance_workbook_escapes_formula_like_names_and_comments(client, attendance_dataset):
    camp, *_ = attendance_dataset

    workbook = load_workbook(BytesIO(attendance_workbook_response(camp).content))
    values = [cell.value for sheet in workbook.worksheets for row in sheet.iter_rows() for cell in row]

    assert "=SUM(1,1)" not in values
    assert "=Family" not in values
    assert all(not isinstance(value, str) or not value.startswith(UNSAFE_FORMULA_PREFIXES) for value in values)


def test_attendance_workbook_isolated_from_other_camps(client, attendance_dataset):
    camp, *_ = attendance_dataset

    workbook = load_workbook(BytesIO(attendance_workbook_response(camp).content))
    exported_text = "\n".join(
        str(cell.value) for sheet in workbook.worksheets for row in sheet.iter_rows() for cell in row if cell.value
    )

    assert "Other Camp" not in exported_text


def test_attendance_workbook_uses_guardian_stay_for_family_member_without_own_dates():
    camp = CampFactory(year=2026, starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 3))
    guardian = ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 1), departure_date=date(2026, 7, 3))
    member = ParticipantFamilyMemberFactory(guardian=guardian, arrival_date=None, departure_date=None)

    workbook = load_workbook(BytesIO(attendance_workbook_response(camp).content))
    sheet = workbook["Anwesenheit"]
    member_row = next(row for row in range(2, sheet.max_row + 1) if sheet.cell(row, 1).value == member.full_name)

    assert [sheet.cell(member_row, column).value for column in range(7, 9)] == ["Anwesend", "Anwesend"]


@pytest.mark.parametrize("missing_dates", [(None, None), (date(2026, 7, 1), None), (None, date(2026, 7, 5))])
def test_attendance_workbook_handles_missing_camp_dates_deterministically(client, missing_dates):
    camp = CampFactory(year=2026, starts_on=missing_dates[0], ends_on=missing_dates[1])

    response = attendance_workbook_response(camp)

    assert response.status_code == 200
    workbook = load_workbook(BytesIO(response.content))
    assert workbook.sheetnames == ["Anwesenheit", "Tagesübersicht"]
    assert [cell.value for cell in workbook["Anwesenheit"][1]] == ["Name", "Alter"]
    assert [cell.value for cell in workbook["Tagesübersicht"][1]] == [
        "Datum",
        "Anwesend",
        "Abwesend",
        "Kommentare",
    ]
