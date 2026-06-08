from decimal import Decimal

import pytest
from django.urls import reverse

from billing.models import PriceRule
from tests.factories import CampFactory, SuperUserFactory


@pytest.mark.django_db
def test_admin_can_manage_camp_flat_rates_without_dropdowns(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    client.force_login(user)

    response = client.post(
        reverse("price-rules-manage", args=[camp.pk]),
        {
            "action": "camp_flat",
            "participant_1w_price": "120.00",
            "participant_1w_foerdersatz": "40",
            "participant_2w_price": "220.00",
            "participant_2w_foerdersatz": "50",
            "companion_1w_price": "80.00",
            "companion_1w_foerdersatz": "20",
            "companion_2w_price": "150.00",
            "companion_2w_foerdersatz": "0",
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
    assert companion_two_weeks.foerdersatz == Decimal("0")
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


@pytest.mark.django_db
def test_price_rule_create_redirects_to_manage_page(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    client.force_login(user)

    response = client.post(
        reverse("price-rule-create", args=[camp.pk]),
        {
            "kind": PriceRule.Kind.DRINK,
            "name": "Fanta",
            "unit_price": "2.50",
            "foerdersatz": "100",
            "applies_to_children": "on",
            "applies_to_adults": "on",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("price-rules-manage", args=[camp.pk])
    assert PriceRule.objects.filter(camp=camp, name="Fanta").exists()


@pytest.mark.django_db
def test_price_rule_edit_redirects_to_manage_page(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    client.force_login(user)

    from tests.factories import PriceRuleFactory

    rule = PriceRuleFactory(kind=PriceRule.Kind.DRINK, name="Cola", unit_price=Decimal("2.00"))

    response = client.post(
        reverse("price-rule-edit", args=[rule.pk]),
        {
            "kind": PriceRule.Kind.DRINK,
            "name": "Cola Light",
            "unit_price": "2.20",
            "foerdersatz": "0",
            "applies_to_children": "on",
            "applies_to_adults": "on",
        },
    )

    rule.refresh_from_db()
    assert response.status_code == 302
    assert response["Location"] == reverse("price-rules-manage", args=[rule.camp.pk])
    assert rule.name == "Cola Light"


@pytest.mark.django_db
def test_price_rule_form_validates_camp_flat_fields():
    from billing.forms import PriceRuleForm

    # valid camp flat
    form = PriceRuleForm(
        {
            "kind": PriceRule.Kind.CAMP_FLAT,
            "name": "Pauschale",
            "unit_price": "100.00",
            "foerdersatz": "0",
            "camp_flat_duration": PriceRule.CampFlatDuration.ONE_WEEK,
            "camp_flat_role": PriceRule.CampFlatRole.PARTICIPANT,
        }
    )
    assert form.is_valid()

    # invalid: missing duration and role
    form = PriceRuleForm(
        {
            "kind": PriceRule.Kind.CAMP_FLAT,
            "name": "Pauschale",
            "unit_price": "100.00",
            "foerdersatz": "0",
            "camp_flat_duration": "",
            "camp_flat_role": "",
        }
    )
    assert not form.is_valid()
    assert "Bitte 1 Woche oder 2 Wochen auswählen." in form.errors["camp_flat_duration"]
    assert "Bitte Teilnehmer oder Begleitperson auswählen." in form.errors["camp_flat_role"]
