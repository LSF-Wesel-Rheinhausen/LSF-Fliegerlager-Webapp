from decimal import Decimal

import pytest
from django.urls import reverse
from tests.factories import CampFactory, SuperUserFactory

from billing.models import PriceRule


@pytest.mark.django_db
def test_admin_can_manage_camp_flat_rates_without_dropdowns(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    client.force_login(user)

    response = client.post(
        reverse("price-rules-manage", args=[camp.pk]),
        {
            "participant_1w_price": "120.00",
            "participant_1w_foerderfaehig": "on",
            "participant_2w_price": "220.00",
            "participant_2w_foerderfaehig": "on",
            "companion_1w_price": "80.00",
            "companion_2w_price": "150.00",
        },
    )

    assert response.status_code == 302
    assert PriceRule.objects.filter(camp=camp, kind=PriceRule.Kind.CAMP_FLAT).count() == 4
    companion_two_weeks = PriceRule.objects.get(
        camp=camp,
        camp_flat_role=PriceRule.CampFlatRole.COMPANION,
        camp_flat_duration=PriceRule.CampFlatDuration.TWO_WEEKS,
    )
    assert companion_two_weeks.unit_price == Decimal("150.00")
    assert companion_two_weeks.foerderfaehig is False
    assert companion_two_weeks.is_default is True


@pytest.mark.django_db
def test_price_rule_manage_page_shows_camp_flat_matrix(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    client.force_login(user)

    response = client.get(reverse("price-rules-manage", args=[camp.pk]))

    assert response.status_code == 200
    assert b"Teilnehmer" in response.content
    assert b"Begleitperson" in response.content
    assert b"1 Woche" in response.content
    assert b"2 Wochen" in response.content
