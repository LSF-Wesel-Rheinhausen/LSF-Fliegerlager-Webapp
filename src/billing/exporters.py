import csv
from io import BytesIO, StringIO

from django.conf import settings

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


def _draw_page_framework(pdf, title, subtitle, participant_name):
    width, height = A4
    
    logo_path = settings.BASE_DIR / "static" / "billing" / "logo.jpg"
    if logo_path.exists():
        pdf.drawImage(str(logo_path), 50, height - 150, width=250, height=100, preserveAspectRatio=True, anchor='nw', mask='auto')

    pdf.setFont("Helvetica", 8)
    pdf.setFillColorRGB(0.3, 0.3, 0.3)
    pdf.drawString(50, height - 165, "Luftsportfreunde Wesel-Rheinhausen e.V. · Postfach 100240 · 46462 Wesel")
    pdf.setFillColorRGB(0, 0, 0)

    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, height - 200, "An:")
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, height - 215, participant_name)

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawRightString(width - 50, height - 70, title)
    
    if subtitle:
        pdf.setFont("Helvetica", 10)
        pdf.setFillColorRGB(0.3, 0.3, 0.3)
        pdf.drawRightString(width - 50, height - 90, subtitle)
        pdf.setFillColorRGB(0, 0, 0)
        
    y = height - 260

    pdf.setFillColorRGB(0.95, 0.95, 0.95)
    pdf.rect(50, y - 6, width - 100, 20, stroke=0, fill=1)
    pdf.setFillColorRGB(0, 0, 0)
    
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(55, y, "Position")
    pdf.drawRightString(width - 120, y, "Menge")
    pdf.drawRightString(width - 55, y, "Summe")
    y -= 15
    
    footer_y = 30
    pdf.setFont("Helvetica", 8)
    pdf.setFillColorRGB(0.5, 0.5, 0.5)
    pdf.drawCentredString(width / 2.0, footer_y, "Erstellt mit der Fliegerlagerabrechnung | Luftsportfreunde Wesel-Rheinhausen e.V.")
    pdf.setFillColorRGB(0, 0, 0)
    
    return y


def _draw_sum_block(pdf, y, items):
    width, _ = A4
    y -= 10
    
    pdf.setStrokeColorRGB(0.5, 0.5, 0.5)
    pdf.line(width - 250, y + 16, width - 50, y + 16)
    pdf.setStrokeColorRGB(0, 0, 0)
    
    for label, value in items:
        if label in ["Förderung", "Gezahlt", "Vorgestreckt"]:
            val_str = f"- {value:.2f} €" if value > 0 else f"{value:.2f} €"
        elif label == "Offen":
            if value > 0:
                label = "Zu zahlen"
                val_str = f"- {value:.2f} €"
            elif value < 0:
                label = "Guthaben"
                val_str = f"+ {abs(value):.2f} €"
            else:
                val_str = "0.00 €"
        else:
            val_str = f"{value:.2f} €"

        is_final = label in ["Zu zahlen", "Guthaben", "Offen"]

        if is_final:
            y -= 4
            pdf.setStrokeColorRGB(0.2, 0.2, 0.2)
            pdf.line(width - 250, y + 14, width - 50, y + 14)
            pdf.setStrokeColorRGB(0, 0, 0)
            pdf.setFont("Helvetica-Bold", 12)
        else:
            pdf.setFont("Helvetica", 11)
        
        pdf.drawString(width - 220, y, f"{label}:")
        pdf.drawRightString(width - 50, y, val_str)
        y -= 18
        
        if is_final:
            pdf.setStrokeColorRGB(0.2, 0.2, 0.2)
            pdf.line(width - 250, y + 14, width - 50, y + 14)
            pdf.setStrokeColorRGB(0, 0, 0)
            
    return y


def participant_pdf_response(participant):
    result = calculate_participant_settlement(participant)
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    width, _ = A4
    
    title = f"Einzelabrechnung {participant.camp.name} {participant.camp.year}"
    y = _draw_page_framework(pdf, title, "", participant.full_name)

    pdf.setFont("Helvetica", 10)
    for line in result.lines:
        if y < 80:
            pdf.showPage()
            y = _draw_page_framework(pdf, title, "", participant.full_name)
            pdf.setFont("Helvetica", 10)
        pdf.drawString(50, y, line.label[:80])
        pdf.drawRightString(width - 120, y, str(line.quantity))
        pdf.drawRightString(width - 50, y, f"{line.total:.2f} €")
        
        pdf.setStrokeColorRGB(0.9, 0.9, 0.9)
        pdf.line(50, y - 5, width - 50, y - 5)
        pdf.setStrokeColorRGB(0, 0, 0)
        y -= 18

    _draw_sum_block(pdf, y, [
        ("Brutto", result.total_gross),
        ("Förderung", result.total_subsidy),
        ("Soll", result.total_due),
        ("Gezahlt", result.total_paid),
        ("Vorgestreckt", result.total_advanced),
        ("Offen", result.balance),
    ])
    
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
    width, _ = A4
    
    title = f"Einzelabrechnung {run.camp.name} {run.camp.year}"
    subtitle = f"Version {run.version} vom {run.created_at:%d.%m.%Y %H:%M}"
    y = _draw_page_framework(pdf, title, subtitle, snapshot.participant_name)

    pdf.setFont("Helvetica", 10)
    for line in snapshot.data.get("lines", []):
        if y < 80:
            pdf.showPage()
            y = _draw_page_framework(pdf, title, subtitle, snapshot.participant_name)
            pdf.setFont("Helvetica", 10)
        pdf.drawString(50, y, str(line.get("label", ""))[:80])
        pdf.drawRightString(width - 120, y, str(line.get("quantity", "")))
        
        try:
            total_val = float(line.get('total', 0.00))
            total_str = f"{total_val:.2f} €"
        except (ValueError, TypeError):
            total_str = f"{line.get('total', '0.00')} €"
            
        pdf.drawRightString(width - 50, y, total_str)
        
        pdf.setStrokeColorRGB(0.9, 0.9, 0.9)
        pdf.line(50, y - 5, width - 50, y - 5)
        pdf.setStrokeColorRGB(0, 0, 0)
        y -= 18

    _draw_sum_block(pdf, y, [
        ("Brutto", snapshot.total_gross),
        ("Förderung", snapshot.total_subsidy),
        ("Soll", snapshot.total_due),
        ("Gezahlt", snapshot.total_paid),
        ("Vorgestreckt", snapshot.total_advanced),
        ("Offen", snapshot.balance),
    ])
    
    pdf.showPage()
    pdf.save()
    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="abrechnung-{snapshot.pk}-v{run.version}.pdf"'
    return response
