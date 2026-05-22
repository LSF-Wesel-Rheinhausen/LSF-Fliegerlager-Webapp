import json

import pytest
from django.urls import reverse
from tests.factories import CampFactory, OvernightCategoryFactory, PriceRuleFactory, SuperUserFactory

from billing.models import PriceRule


@pytest.mark.django_db
def test_price_rule_manage_page_shows_overnight_categories_and_no_legacy_matrix(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    OvernightCategoryFactory(camp=camp, name="Teilnehmer 1 Woche")
    client.force_login(user)

    response = client.get(reverse("price-rules-manage", args=[camp.pk]))

    assert response.status_code == 200
    assert b"Uebernachtungskategorien" in response.content
    assert b"Teilnehmer 1 Woche" in response.content
    assert b"Lagerpauschalen speichern" not in response.content


@pytest.mark.django_db
def test_price_rule_overlay_get_for_drink_shows_compact_category_specific_form(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    client.force_login(user)

    response = client.get(
        reverse("price-rule-create", args=[camp.pk]),
        {"kind": PriceRule.Kind.DRINK, "overlay": "1"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    content = response.content.decode()

    assert response.status_code == 200
    assert "Getränk anlegen" in content
    assert 'name="overlay" value="1"' in content
    assert f'action="{reverse("price-rule-create", args=[camp.pk])}?kind=drink&amp;overlay=1"' in content
    assert 'name="kind" value="drink"' in content
    assert "Uebernachtungskategorie" not in content
    assert "Art" not in content
    assert "Weitere Optionen" in content
    assert "Preise verwalten" not in content


@pytest.mark.django_db
def test_camp_flat_overlay_requires_overnight_category(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    client.force_login(user)

    response = client.post(
        reverse("price-rule-create", args=[camp.pk]),
        {"kind": PriceRule.Kind.CAMP_FLAT, "overlay": "1", "name": "Pauschale", "unit_price": "120.00"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    content = response.content.decode()

    assert response.status_code == 200
    assert "Lagerpauschale anlegen" in content
    assert "Bitte eine Uebernachtungskategorie" in content
    assert "Preise verwalten" not in content


@pytest.mark.django_db
def test_valid_camp_flat_overlay_post_returns_json_and_updates_section(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    category = OvernightCategoryFactory(camp=camp, name="Teilnehmer 1 Woche")
    client.force_login(user)

    response = client.post(
        reverse("price-rule-create", args=[camp.pk]),
        {
            "kind": PriceRule.Kind.CAMP_FLAT,
            "overlay": "1",
            "name": "Teilnehmer 1 Woche",
            "overnight_category": category.pk,
            "unit_price": "120.00",
            "foerderfaehig": "on",
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    payload = json.loads(response.content)
    rule = PriceRule.objects.get(camp=camp, name="Teilnehmer 1 Woche")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert payload["success"] is True
    assert payload["section_id"] == "prices-camp-flat"
    assert "Teilnehmer 1 Woche" in payload["sections_html"]
    assert rule.kind == PriceRule.Kind.CAMP_FLAT
    assert rule.overnight_category == category


@pytest.mark.django_db
def test_valid_price_rule_overlay_post_returns_json_and_updates_drink_section(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    client.force_login(user)

    response = client.post(
        reverse("price-rule-create", args=[camp.pk]),
        {
            "kind": PriceRule.Kind.DRINK,
            "overlay": "1",
            "name": "Apfelschorle",
            "unit_price": "2.30",
            "foerderfaehig": "on",
            "applies_to_children": "on",
            "applies_to_adults": "on",
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    payload = json.loads(response.content)
    rule = PriceRule.objects.get(camp=camp, name="Apfelschorle")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert payload["success"] is True
    assert payload["section_id"] == "prices-drinks"
    assert "Apfelschorle" in payload["sections_html"]
    assert rule.kind == PriceRule.Kind.DRINK
    assert rule.foerderfaehig is True
    assert rule.applies_to_children is True
    assert rule.applies_to_adults is True
    assert rule.is_default is False


@pytest.mark.django_db
def test_price_rule_overlay_edit_uses_existing_category_and_value(client):
    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    category = OvernightCategoryFactory(camp=camp, name="Teilnehmer 1 Woche")
    rule = PriceRuleFactory(
        camp=camp,
        overnight_category=category,
        kind=PriceRule.Kind.CAMP_FLAT,
        name="Lagerpauschale",
    )
    client.force_login(user)

    response = client.get(
        reverse("price-rule-edit", args=[rule.pk]),
        {"overlay": "1"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    content = response.content.decode()

    assert response.status_code == 200
    assert "Lagerpauschale bearbeiten" in content
    assert 'value="Lagerpauschale"' in content
    assert 'name="kind" value="camp_flat"' in content
    assert "Uebernachtungskategorie" in content
