import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.urls import reverse

from tests.factories import CampFactory, ParticipantFactory, PaymentFactory, SuperUserFactory


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
    assert "IBAN oder PayPal" in content


@pytest.mark.django_db
def test_base_layout_renders_favicon(client):
    client.force_login(SuperUserFactory())

    response = client.get(reverse("camp-list"))

    assert response.status_code == 200
    assert 'rel="icon"' in response.content.decode("utf-8")
    assert "billing/icons/admin-icon-192.png" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_pdf_links_open_directly_without_embedded_preview(client):
    participant = ParticipantFactory()
    client.force_login(SuperUserFactory())

    response = client.get(reverse("participant-detail", args=[participant.pk]))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'target="_blank"' in content
    assert 'rel="noopener"' in content
    assert "data-pdf-popup" not in content
    assert "global-pdf-iframe" not in content
