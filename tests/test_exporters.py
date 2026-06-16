import csv
from decimal import Decimal
from io import BytesIO, StringIO

import pytest
from django.urls import reverse
from openpyxl import load_workbook

from billing.models import Charge, Expense
from billing.permissions import EDITOR_GROUP
from tests.factories import (
    CampFactory,
    ChargeFactory,
    DrinkEntryFactory,
    ExpenseFactory,
    GroupFactory,
    ParticipantFactory,
    PaymentFactory,
    SuperUserFactory,
    UserFactory,
)


@pytest.fixture
def export_dataset():
    camp = CampFactory(year=2026)
    participant = ParticipantFactory(
        camp=camp,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.test",
        phone="01234",
        actual_nights=5,
    )
    ChargeFactory(
        participant=participant,
        kind=Charge.Kind.DRINK,
        description="Cola",
        quantity=Decimal("2.00"),
        unit_price=Decimal("2.50"),
    )
    ChargeFactory(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=Decimal("1.00"),
        unit_price=Decimal("7.00"),
    )
    DrinkEntryFactory(
        participant=participant,
        quantity=3,
        unit_price=Decimal("1.50"),
    )
    PaymentFactory(participant=participant, amount=Decimal("4.00"))
    ExpenseFactory(participant=participant, amount=Decimal("3.00"), status=Expense.Status.APPROVED)
    return camp, participant


def csv_rows(response):
    return list(csv.reader(StringIO(response.content.decode("utf-8"))))


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "arg_getter"),
    [
        ("export-settlements-csv", lambda camp, _participant: [camp.pk]),
        ("export-drinks-csv", lambda camp, _participant: [camp.pk]),
        ("export-workbook", lambda camp, _participant: [camp.pk]),
        ("participant-import-template", lambda camp, _participant: [camp.pk]),
        ("export-participant-pdf", lambda _camp, participant: [participant.pk]),
    ],
)
def test_export_routes_require_editor_access(client, export_dataset, route_name, arg_getter):
    camp, participant = export_dataset
    url = reverse(route_name, args=arg_getter(camp, participant))

    anonymous_response = client.get(url)

    assert anonymous_response.status_code == 302
    assert reverse("login") in anonymous_response["Location"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "arg_getter"),
    [
        ("export-settlements-csv", lambda camp, _participant: [camp.pk]),
        ("export-drinks-csv", lambda camp, _participant: [camp.pk]),
        ("export-workbook", lambda camp, _participant: [camp.pk]),
        ("participant-import-template", lambda camp, _participant: [camp.pk]),
        ("export-participant-pdf", lambda _camp, participant: [participant.pk]),
    ],
)
@pytest.mark.parametrize("user_kind", ["editor", "admin"])
def test_export_routes_allow_editor_and_admin_access(client, export_dataset, route_name, arg_getter, user_kind):
    camp, participant = export_dataset
    if user_kind == "admin":
        user = SuperUserFactory(username="admin")
    else:
        user = UserFactory(username="editor")
        user.groups.add(GroupFactory(name=EDITOR_GROUP))
    client.force_login(user)

    response = client.get(reverse(route_name, args=arg_getter(camp, participant)))

    assert response.status_code == 200


@pytest.mark.django_db
def test_settlement_csv_exports_calculated_kiosk_charges_payments_and_expenses(client, export_dataset):
    camp, _participant = export_dataset
    client.force_login(SuperUserFactory())

    response = client.get(reverse("export-settlements-csv", args=[camp.pk]))

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response["Content-Disposition"] == 'attachment; filename="abrechnung-2026.csv"'
    assert csv_rows(response) == [
        ["Nachname", "Vorname", "Brutto", "Förderung", "Soll", "Gezahlt", "Vorgestreckt", "Offen"],
        ["Lovelace", "Ada", "16.50", "0.00", "16.50", "4.00", "3.00", "9.50"],
    ]


@pytest.mark.django_db
def test_participant_import_template_export_contains_headers_and_examples(client, export_dataset):
    camp, _participant = export_dataset
    client.force_login(SuperUserFactory())

    response = client.get(reverse("participant-import-template", args=[camp.pk]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert response["Content-Disposition"] == 'attachment; filename="teilnehmer_import_vorlage.xlsx"'

    wb = load_workbook(BytesIO(response.content))
    assert "Teilnehmer" in wb.sheetnames

    sheet = wb["Teilnehmer"]
    # Check headers
    headers = [cell.value for cell in sheet[1]]
    assert headers[:6] == ["Vorname*", "Nachname*", "Anreise*", "Abreise*", "Hilfssatz*", "Berufssatz*"]
    assert "Email" in headers
    assert "Notizen" in headers

    # Check that there is at least one example row
    assert sheet.max_row >= 2
    assert sheet.cell(row=2, column=1).value == "Max"
    assert sheet.cell(row=2, column=2).value == "Mustermann"


@pytest.mark.django_db
def test_drinks_csv_exports_legacy_entries_and_kiosk_drink_charges(client, export_dataset):
    camp, _participant = export_dataset
    client.force_login(SuperUserFactory())

    response = client.get(reverse("export-drinks-csv", args=[camp.pk]))

    rows = csv_rows(response)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response["Content-Disposition"] == 'attachment; filename="getraenke-2026.csv"'
    assert rows[0] == ["Nachname", "Vorname", "Getränk", "Menge", "Einzelpreis", "Summe", "Erfasst am"]
    assert rows[1][:6] == ["Lovelace", "Ada", "Wasser", "3", "1.50", "4.50"]
    assert rows[2][:6] == ["Lovelace", "Ada", "Cola", "2.00", "2.50", "5.00"]


@pytest.mark.django_db
def test_workbook_export_contains_settlement_and_participant_sheets(client, export_dataset):
    camp, _participant = export_dataset
    client.force_login(SuperUserFactory())

    response = client.get(reverse("export-workbook", args=[camp.pk]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert response["Content-Disposition"] == 'attachment; filename="fliegerlager-2026.xlsx"'

    workbook = load_workbook(BytesIO(response.content), data_only=True)
    assert workbook.sheetnames == ["Abrechnung", "Teilnehmer", "Kostenstellen"]
    settlement_sheet = workbook["Abrechnung"]
    assert [cell.value for cell in settlement_sheet[1]] == [
        "Nachname",
        "Vorname",
        "Brutto",
        "Förderung",
        "Soll",
        "Gezahlt",
        "Vorgestreckt",
        "Offen",
    ]
    assert settlement_sheet["A2"].value == "Lovelace"
    assert settlement_sheet["B2"].value == "Ada"
    assert Decimal(str(settlement_sheet["C2"].value)) == Decimal("16.5")
    assert Decimal(str(settlement_sheet["H2"].value)) == Decimal("9.5")

    participants_sheet = workbook["Teilnehmer"]
    assert participants_sheet["A2"].value == "Lovelace"
    assert participants_sheet["B2"].value == "Ada"
    assert participants_sheet["C2"].value == "ada@example.test"
    assert participants_sheet["D2"].value == "01234"
    assert participants_sheet["H2"].value == 5


@pytest.mark.django_db
def test_participant_pdf_export_returns_pdf_download(client, export_dataset):
    _camp, participant = export_dataset
    client.force_login(SuperUserFactory())

    response = client.get(reverse("export-participant-pdf", args=[participant.pk]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == f'attachment; filename="abrechnung-{participant.pk}.pdf"'
    assert response.content.startswith(b"%PDF-")
