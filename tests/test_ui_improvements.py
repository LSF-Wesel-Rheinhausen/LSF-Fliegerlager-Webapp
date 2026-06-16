import pytest
from decimal import Decimal
from django.urls import reverse
from tests.factories import CampFactory, ParticipantFactory, PaymentFactory, SuperUserFactory

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
