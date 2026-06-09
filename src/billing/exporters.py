import csv
from io import BytesIO, StringIO

from django.http import HttpResponse
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .models import Charge, DrinkEntry, Participant, Settlement, SettlementRun
from .services import calculate_camp_settlements, calculate_participant_settlement, money


def csv_response(filename, rows, headers):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def camp_settlement_csv(camp):
    rows = []
    for result in calculate_camp_settlements(camp):
        rows.append(
            [
                result.participant.last_name,
                result.participant.first_name,
                result.total_gross,
                result.total_subsidy,
                result.total_due,
                result.total_paid,
                result.total_advanced,
                result.balance,
            ]
        )
    return csv_response(
        f"abrechnung-{camp.year}.csv",
        rows,
        ["Nachname", "Vorname", "Brutto", "Förderung", "Soll", "Gezahlt", "Vorgestreckt", "Offen"],
    )


def drink_entries_csv(camp):
    rows = []
    legacy_entries = DrinkEntry.objects.filter(participant__camp=camp).select_related("participant")
    kiosk_charges = Charge.objects.filter(
        participant__camp=camp,
        kind=Charge.Kind.DRINK,
        deleted_at__isnull=True,
    ).select_related("participant")
    for entry in legacy_entries:
        rows.append(
            [
                entry.participant.last_name,
                entry.participant.first_name,
                entry.get_drink_display(),
                entry.quantity,
                entry.unit_price,
                entry.total,
                entry.booked_at,
            ]
        )
    for entry in kiosk_charges:
        rows.append(
            [
                entry.participant.last_name,
                entry.participant.first_name,
                entry.description,
                entry.quantity,
                entry.unit_price,
                money(entry.total),
                entry.created_at,
            ]
        )
    return csv_response(
        f"getraenke-{camp.year}.csv",
        rows,
        ["Nachname", "Vorname", "Getränk", "Menge", "Einzelpreis", "Summe", "Erfasst am"],
    )


def camp_workbook_response(camp):
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Abrechnung"
    summary.append(["Nachname", "Vorname", "Brutto", "Förderung", "Soll", "Gezahlt", "Vorgestreckt", "Offen"])
    for result in calculate_camp_settlements(camp):
        summary.append(
            [
                result.participant.last_name,
                result.participant.first_name,
                result.total_gross,
                result.total_subsidy,
                result.total_due,
                result.total_paid,
                result.total_advanced,
                result.balance,
            ]
        )

    participants = workbook.create_sheet("Teilnehmer")
    participants.append(["Nachname", "Vorname", "E-Mail", "Telefon", "Status", "Hilfssatz", "Berufssatz", "Nächte"])
    for participant in Participant.objects.filter(camp=camp):
        participants.append(
            [
                participant.last_name,
                participant.first_name,
                participant.email,
                participant.phone,
                participant.get_status_display(),
                participant.hilfssatz,
                participant.berufssatz,
                participant.actual_nights,
            ]
        )

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="fliegerlager-{camp.year}.xlsx"'
    return response


def participant_pdf_response(participant):
    result = calculate_participant_settlement(participant)
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    width, height = A4
    y = height - 60

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, y, f"Einzelabrechnung {participant.camp.name} {participant.camp.year}")
    y -= 35
    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, y, f"Teilnehmer: {participant.full_name}")
    y -= 30

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y, "Position")
    pdf.drawRightString(420, y, "Menge")
    pdf.drawRightString(500, y, "Summe")
    y -= 18
    pdf.setFont("Helvetica", 10)
    for line in result.lines:
        if y < 80:
            pdf.showPage()
            y = height - 60
            pdf.setFont("Helvetica", 10)
        pdf.drawString(50, y, line.label[:60])
        pdf.drawRightString(420, y, str(line.quantity))
        pdf.drawRightString(500, y, f"{line.total:.2f} EUR")
        y -= 16

    y -= 12
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(500, y, f"Brutto: {result.total_gross:.2f} EUR")
    y -= 18
    pdf.drawRightString(500, y, f"Förderung: {result.total_subsidy:.2f} EUR")
    y -= 18
    pdf.drawRightString(500, y, f"Soll: {result.total_due:.2f} EUR")
    y -= 18
    pdf.drawRightString(500, y, f"Gezahlt: {result.total_paid:.2f} EUR")
    y -= 18
    pdf.drawRightString(500, y, f"Vorgestreckt: {result.total_advanced:.2f} EUR")
    y -= 18
    pdf.drawRightString(500, y, f"Offen: {result.balance:.2f} EUR")
    pdf.showPage()
    pdf.save()

    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="abrechnung-{participant.pk}.pdf"'
    return response


def settlement_run_csv(run: SettlementRun) -> HttpResponse:
    rows = [
        [
            snapshot.participant_name,
            snapshot.total_gross,
            snapshot.total_subsidy,
            snapshot.total_due,
            snapshot.total_paid,
            snapshot.total_advanced,
            snapshot.balance,
        ]
        for snapshot in run.settlements.all()
    ]
    return csv_response(
        f"abrechnung-{run.camp.year}-v{run.version}.csv",
        rows,
        ["Teilnehmer", "Brutto", "Förderung", "Soll", "Gezahlt", "Vorgestreckt", "Offen"],
    )


def settlement_run_workbook_response(run: SettlementRun) -> HttpResponse:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Abrechnung"
    summary.append(["Teilnehmer", "Status", "Brutto", "Förderung", "Soll", "Gezahlt", "Vorgestreckt", "Offen"])
    for snapshot in run.settlements.all():
        summary.append(
            [
                snapshot.participant_name,
                snapshot.data.get("participant", {}).get("status_label", snapshot.participant_status),
                snapshot.total_gross,
                snapshot.total_subsidy,
                snapshot.total_due,
                snapshot.total_paid,
                snapshot.total_advanced,
                snapshot.balance,
            ]
        )
    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="abrechnung-{run.camp.year}-v{run.version}.xlsx"'
    return response


def settlement_snapshot_pdf_response(snapshot: Settlement) -> HttpResponse:
    run = snapshot.run
    if run is None:
        raise ValueError("Historical settlement PDF requires a versioned run.")
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    _width, height = A4
    y = height - 60
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, y, f"Einzelabrechnung {run.camp.name} {run.camp.year}")
    y -= 24
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, y, f"Version {run.version} vom {run.created_at:%d.%m.%Y %H:%M}")
    y -= 28
    pdf.drawString(50, y, f"Teilnehmer: {snapshot.participant_name}")
    y -= 28
    for line in snapshot.data.get("lines", []):
        if y < 80:
            pdf.showPage()
            y = height - 60
            pdf.setFont("Helvetica", 10)
        pdf.drawString(50, y, str(line.get("label", ""))[:60])
        pdf.drawRightString(420, y, str(line.get("quantity", "")))
        pdf.drawRightString(500, y, f"{line.get('total', '0.00')} EUR")
        y -= 16
    y -= 12
    pdf.setFont("Helvetica-Bold", 11)
    for label, value in (
        ("Brutto", snapshot.total_gross),
        ("Förderung", snapshot.total_subsidy),
        ("Soll", snapshot.total_due),
        ("Gezahlt", snapshot.total_paid),
        ("Vorgestreckt", snapshot.total_advanced),
        ("Offen", snapshot.balance),
    ):
        pdf.drawRightString(500, y, f"{label}: {value:.2f} EUR")
        y -= 18
    pdf.showPage()
    pdf.save()
    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="abrechnung-{snapshot.pk}-v{run.version}.pdf"'
    return response
