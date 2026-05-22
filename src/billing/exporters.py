import csv
from io import BytesIO, StringIO

from django.http import HttpResponse
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .models import Charge, DrinkEntry, Participant
from .services import calculate_camp_settlements, calculate_participant_settlement


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
    kiosk_charges = Charge.objects.filter(participant__camp=camp, kind=Charge.Kind.DRINK).select_related("participant")
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
                entry.total,
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
