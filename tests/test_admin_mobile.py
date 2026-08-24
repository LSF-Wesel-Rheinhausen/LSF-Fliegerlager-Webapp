import pytest
from django.urls import reverse

from billing.models import MealOrder, Participant, Shift
from tests.factories import CampFactory, ParticipantFactory, SuperUserFactory


@pytest.mark.django_db
@pytest.mark.parametrize("model_name", ["participant", "mealorder", "shift"])
def test_admin_changelists_expose_mobile_navigation_and_filter_controls(client, model_name):
    client.force_login(SuperUserFactory())

    response = client.get(reverse(f"admin:billing_{model_name}_changelist"))

    assert response.status_code == 200
    assert b"admin-mobile-menu-toggle" in response.content
    assert b'aria-controls="admin-nav-drawer"' in response.content
    assert b"admin-filter-toggle" in response.content
    assert b'aria-controls="changelist-filter"' in response.content
    assert b"admin-filter-summary" in response.content
    assert b"admin-empty-state" in response.content


@pytest.mark.django_db
def test_participant_admin_keeps_long_values_in_scrollable_results_and_german_labels(client):
    admin = SuperUserFactory()
    camp = CampFactory(name="Lager mit einem bewusst langen Namen fuer die mobile Tabelle")
    participant = ParticipantFactory(
        camp=camp,
        first_name="Vorname mit einem sehr langen Wert fuer kleine Viewports",
        last_name="Nachname",
    )
    client.force_login(admin)

    response = client.get(reverse("admin:billing_participant_changelist"))

    assert response.status_code == 200
    assert participant.first_name.encode() in response.content
    assert b"Teilnehmer" in response.content
    assert b"Nachname" in response.content
    assert b"admin-results-scroll" in response.content
    assert b"Keine Teilnehmer" not in response.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("model", "url_name", "label", "has_add_action"),
    [
        (MealOrder, "mealorder", b"Essensbestellungen", False),
        (Shift, "shift", b"Dienste", True),
        (Participant, "participant", b"Teilnehmer", True),
    ],
)
def test_admin_empty_state_is_german_and_explains_next_step(client, model, url_name, label, has_add_action):
    client.force_login(SuperUserFactory())
    response = client.get(reverse(f"admin:billing_{url_name}_changelist"))

    assert response.status_code == 200
    assert label in response.content
    assert b"Noch keine" in response.content
    assert (b"admin-empty-state__action" in response.content) is has_add_action
