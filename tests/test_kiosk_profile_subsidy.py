from decimal import Decimal

import pytest
from django.urls import reverse

from billing.kiosk_access import KIOSK_FAMILY_MEMBER_SESSION_KEY
from billing.models import ParticipantFamilyMember, PriceRule
from billing.services import participant_profile_subsidies, participant_subsidy_rate
from tests.factories import ParticipantFactory, ParticipantFamilyMemberFactory, PriceRuleFactory
from tests.kiosk_helpers import authenticate_kiosk_session


def _set_kiosk_identity(client, *, participant, family_member=None):
    session = client.session
    authenticate_kiosk_session(session, participant, family_member=family_member)
    session.save()


def _profile_url(route_name, participant):
    return reverse(route_name, kwargs={"participant_id": participant.pk})


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["kiosk-profile", "central-kiosk-profile"])
def test_youth_profile_displays_its_own_factors_and_each_applicable_price_rule(kiosk_client, route_name):
    participant = ParticipantFactory(
        is_youth_group=True,
        hilfssatz=Decimal("0.5000"),
        berufssatz=Decimal("0.5000"),
    )
    first_rule = PriceRuleFactory(
        camp=participant.camp,
        name="Lagerbeitrag",
        kind=PriceRule.Kind.CAMP_FLAT,
        foerdersatz=Decimal("0.8000"),
    )
    second_rule = PriceRuleFactory(
        camp=participant.camp,
        name="Abendessen",
        kind=PriceRule.Kind.MEAL,
        foerdersatz=Decimal("0.5000"),
    )
    PriceRuleFactory(camp=participant.camp, name="Nur für Kinder", applies_to_adults=False)
    PriceRuleFactory(camp=participant.camp, name="Archiviert", is_archived=True)
    _set_kiosk_identity(kiosk_client, participant=participant)

    response = kiosk_client.get(_profile_url(route_name, participant))

    assert response.status_code == 200
    profile = response.context["subsidy_profile"]
    assert profile["hilfssatz"] == Decimal("0.5000")
    assert profile["berufssatz"] == Decimal("0.5000")
    assert [(entry.price_rule.pk, entry.effective_rate) for entry in profile["price_rules"]] == [
        (first_rule.pk, Decimal("0.2000")),
        (second_rule.pk, Decimal("0.1250")),
    ]
    content = response.content.decode()
    assert "data-profile-subsidy" in content
    assert "Hilfssatz" in content and "50 %" in content
    assert "Berufssatz" in content
    assert "Lagerbeitrag" in content and "20 %" in content
    assert "Abendessen" in content and "12.5 %" in content
    assert "Nur für Kinder" not in content
    assert "Archiviert" not in content


@pytest.mark.django_db
def test_zero_factor_is_rendered_as_a_real_zero_subsidy(kiosk_client):
    participant = ParticipantFactory(is_youth_group=True, hilfssatz=Decimal("0.0000"), berufssatz=Decimal("0.7000"))
    PriceRuleFactory(camp=participant.camp, name="Förderfähiger Beitrag", foerdersatz=Decimal("0.9000"))
    _set_kiosk_identity(kiosk_client, participant=participant)

    response = kiosk_client.get(_profile_url("kiosk-profile", participant))

    assert response.status_code == 200
    assert "0 %" in response.content.decode()
    assert response.context["subsidy_profile"]["price_rules"][0].effective_rate == Decimal("0.0000")


@pytest.mark.django_db
def test_subsidy_service_caps_effective_rate_at_one_hundred_percent():
    participant = ParticipantFactory(is_youth_group=True, hilfssatz=Decimal("1.0000"), berufssatz=Decimal("1.0000"))

    assert participant_subsidy_rate(participant, Decimal("1.2500")) == Decimal("1.0000")


@pytest.mark.django_db
def test_non_youth_profile_keeps_existing_zero_rate_and_hides_youth_breakdown(kiosk_client):
    participant = ParticipantFactory(
        is_youth_group=False,
        hilfssatz=Decimal("0.8000"),
        berufssatz=Decimal("0.9000"),
    )
    rule = PriceRuleFactory(camp=participant.camp, foerdersatz=Decimal("0.7500"))
    _set_kiosk_identity(kiosk_client, participant=participant)

    response = kiosk_client.get(_profile_url("kiosk-profile", participant))

    assert response.status_code == 200
    assert response.context["subsidy_profile"] is None
    assert "data-profile-subsidy" not in response.content.decode()
    assert participant_subsidy_rate(participant, rule.foerdersatz) == Decimal("0.0000")
    assert participant_profile_subsidies(participant) == []


@pytest.mark.django_db
def test_family_member_profile_never_displays_guardian_factors_as_family_rates(kiosk_client):
    guardian = ParticipantFactory(
        is_youth_group=True,
        hilfssatz=Decimal("0.8500"),
        berufssatz=Decimal("0.7500"),
    )
    child = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role=ParticipantFamilyMember.Role.CHILD,
        is_youth_group=True,
    )
    PriceRuleFactory(camp=guardian.camp, name="Guardians Förderregel", foerdersatz=Decimal("0.8000"))
    _set_kiosk_identity(kiosk_client, participant=guardian)

    response = kiosk_client.get(reverse("kiosk-family-member-profile", kwargs={"family_member_id": child.pk}))

    assert response.status_code == 200
    assert KIOSK_FAMILY_MEMBER_SESSION_KEY not in kiosk_client.session
    assert response.context["subsidy_profile"] is None
    content = response.content.decode()
    assert "data-profile-subsidy" not in content
    assert "Guardians Förderregel" not in content
    assert "85 %" not in content
    assert "75 %" not in content


@pytest.mark.django_db
def test_companion_identity_does_not_inherit_guardian_subsidy_display(kiosk_client):
    guardian = ParticipantFactory(
        is_youth_group=True,
        hilfssatz=Decimal("0.8500"),
        berufssatz=Decimal("0.7500"),
    )
    companion = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    _set_kiosk_identity(kiosk_client, participant=guardian, family_member=companion)

    response = kiosk_client.get(reverse("kiosk-family-member-profile", kwargs={"family_member_id": companion.pk}))

    assert response.status_code == 200
    assert KIOSK_FAMILY_MEMBER_SESSION_KEY in kiosk_client.session
    assert response.context["subsidy_profile"] is None
    assert "data-profile-subsidy" not in response.content.decode()


@pytest.mark.django_db
def test_profile_post_cannot_change_subsidy_factors(kiosk_client):
    participant = ParticipantFactory(
        is_youth_group=True,
        hilfssatz=Decimal("0.4000"),
        berufssatz=Decimal("0.6000"),
    )
    _set_kiosk_identity(kiosk_client, participant=participant)

    response = kiosk_client.post(
        _profile_url("kiosk-profile", participant),
        {
            "first_name": participant.first_name,
            "last_name": participant.last_name,
            "email": participant.email,
            "phone": participant.phone,
            "hilfssatz": "1.0000",
            "berufssatz": "1.0000",
        },
    )

    assert response.status_code == 302
    participant.refresh_from_db()
    assert participant.hilfssatz == Decimal("0.4000")
    assert participant.berufssatz == Decimal("0.6000")
