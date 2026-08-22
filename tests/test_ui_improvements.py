import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from tests.factories import CampFactory, ExpenseFactory, ParticipantFactory, PaymentFactory, SuperUserFactory


def test_template_theme_properties_are_defined_in_the_shared_stylesheet():
    project_root = Path(__file__).resolve().parents[1]
    stylesheet = (project_root / "src/static/billing/app-v8.css").read_text(encoding="utf-8")
    templates = "\n".join(path.read_text(encoding="utf-8") for path in (project_root / "src/templates").rglob("*.html"))

    defined_properties = set(re.findall(r"(--[a-z0-9-]+)\s*:", stylesheet))
    used_properties = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", templates))

    assert used_properties <= defined_properties, (
        f"Templates reference undefined theme properties: {sorted(used_properties - defined_properties)}"
    )


@pytest.mark.django_db
def test_participant_detail_shows_donation_prompt_for_credit(client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Guthaben", last_name="Mensch")
    # Pay more than due (which is 0 here) -> creates a credit balance
    PaymentFactory(participant=participant, amount=Decimal("50.00"))

    client.force_login(SuperUserFactory())
    response = client.get(reverse("participant-detail", args=[participant.pk]))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Möchtest du das Guthaben" in content
    assert "IBAN oder PayPal" not in content


@pytest.mark.django_db
def test_base_layout_renders_favicon(client):
    client.force_login(SuperUserFactory())

    response = client.get(reverse("camp-list"))

    assert response.status_code == 200
    assert 'rel="icon"' in response.content.decode("utf-8")
    assert "billing/icons/admin-icon-192.png" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_pdf_links_use_a_closable_embedded_preview_with_external_fallback(client):
    participant = ParticipantFactory()
    client.force_login(SuperUserFactory())

    response = client.get(reverse("participant-detail", args=[participant.pk]))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'data-pdf-preview="true"' in content
    assert 'id="global-pdf-dialog"' in content
    assert 'id="global-pdf-iframe"' in content
    assert "data-pdf-open-external" in content
    assert 'target="_blank"' in content
    assert 'rel="noopener"' in content


@pytest.mark.django_db
def test_admin_receipt_links_expose_server_derived_preview_types_and_context(client):
    camp = CampFactory()
    image_expense = ExpenseFactory(
        camp=camp,
        participant__camp=camp,
        description="Belegbild Küche",
        receipt=SimpleUploadedFile("kueche.jpg", b"image", content_type="image/jpeg"),
    )
    pdf_expense = ExpenseFactory(
        camp=camp,
        participant__camp=camp,
        description="Beleg PDF",
        receipt=SimpleUploadedFile("rechnung.pdf", b"pdf", content_type="application/pdf"),
    )
    unknown_expense = ExpenseFactory(
        camp=camp,
        participant__camp=camp,
        description="Unbekannter Beleg",
        receipt=SimpleUploadedFile("beleg.bin", b"binary", content_type="application/octet-stream"),
    )
    client.force_login(SuperUserFactory())

    response = client.get(reverse("camp-detail", args=[camp.pk]))
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert 'data-receipt-preview="image"' in content
    assert 'data-receipt-alt="Belegbild Küche"' in content
    assert 'data-pdf-preview="true"' in content
    assert 'data-receipt-preview=""' not in content
    unknown_link_start = content.index(reverse("expense-receipt", args=[unknown_expense.pk]))
    unknown_link = content[unknown_link_start : content.index(">", unknown_link_start)]
    assert 'target="_blank"' in unknown_link
    assert "data-receipt-preview" not in unknown_link
    assert image_expense.receipt.name.encode() not in response.content
    assert pdf_expense.receipt.name.encode() not in response.content


def test_receipt_image_dialog_contract_is_accessible_and_preserves_pdf_dialog():
    project_root = Path(__file__).resolve().parents[1]
    dialog = (project_root / "src/templates/includes/receipt_preview_dialog.html").read_text(encoding="utf-8")
    script = (project_root / "src/static/billing/pwa.js").read_text(encoding="utf-8")

    assert 'id="global-receipt-dialog"' in dialog
    assert 'aria-labelledby="global-receipt-dialog-title"' in dialog
    assert 'id="global-receipt-image"' in dialog
    assert 'alt=""' in dialog
    assert "data-receipt-open-external" in dialog
    assert 'a[data-receipt-preview="image"]' in script
    assert "event.button !== 0" in script
    assert "imageTrigger" in script
    assert "global-pdf-dialog" in script
