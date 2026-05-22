from decimal import Decimal

import pytest
from django.urls import reverse
from tests.factories import (
    CampFactory,
    OvernightCategoryFactory,
    ParticipantFactory,
    PriceRuleFactory,
    SuperUserFactory,
)

from billing.models import Camp, Participant, PriceRule, SettlementRun
from billing.services import create_settlement_run


@pytest.mark.django_db
def test_admin_can_delete_camp_after_confirmation(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory(name="Sommerlager")
    category = OvernightCategoryFactory(camp=camp, name="Teilnehmer 1 Woche")
    participant = ParticipantFactory(camp=camp, overnight_category=category)
    PriceRuleFactory(
        camp=camp,
        overnight_category=category,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Lagerpauschale",
        unit_price=Decimal("120.00"),
        is_default=True,
    )
    create_settlement_run(camp, user)
    client.force_login(user)

    confirm_response = client.get(reverse("camp-delete", args=[camp.pk]))
    response = client.post(reverse("camp-delete", args=[camp.pk]))

    assert confirm_response.status_code == 200
    assert "Lager löschen" in confirm_response.content.decode()
    assert response.status_code == 302
    assert response["Location"] == reverse("camp-list")
    assert Camp.objects.filter(pk=camp.pk).exists() is False
    assert Participant.objects.filter(pk=participant.pk).exists() is False
    assert PriceRule.objects.filter(camp=camp).exists() is False
    assert SettlementRun.objects.filter(camp=camp).exists() is False
