from datetime import date

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from billing.permissions import ADMIN_GROUP, EDITOR_GROUP
from tests.factories import CampFactory, ParticipantFactory, SuperUserFactory, UserFactory


@pytest.mark.django_db
def test_anonymous_application_login_keeps_the_unscoped_public_shell(client):
    UserFactory()
    response = client.get(reverse("login"))

    assert response.status_code == 200
    assert b'<main id="main-content" class="page" tabindex="-1">' in response.content
    assert b"camp-task-nav" not in response.content
    assert b"admin-global-menu" not in response.content


@pytest.mark.django_db
def test_camp_task_navigation_groups_existing_actions_and_keeps_admin_links_gated(client):
    camp = CampFactory()
    editor = UserFactory()
    editor.groups.add(Group.objects.get_or_create(name=EDITOR_GROUP)[0])
    client.force_login(editor)

    response = client.get(reverse("camp-detail", args=[camp.pk]))

    assert response.status_code == 200
    assert b'class="camp-task-nav"' in response.content
    assert b"Teilnehmende" in response.content
    assert b"Finanzen" in response.content
    assert b"Teilnehmer anlegen" in response.content
    assert b"Lager bearbeiten" in response.content
    assert b"Anwesenheitsmappe" not in response.content
    assert "Essensübersicht".encode() in response.content
    assert b"Berichte und Einstellungen" not in response.content
    assert b"Lager-PIN" not in response.content


@pytest.mark.django_db
def test_admin_role_sees_report_and_configuration_links_in_camp_task_navigation(client):
    camp = CampFactory()
    admin = UserFactory()
    admin.groups.add(Group.objects.get_or_create(name=ADMIN_GROUP)[0])
    client.force_login(admin)

    response = client.get(reverse("camp-detail", args=[camp.pk]))

    assert response.status_code == 200
    assert b"Berichte und Einstellungen" in response.content
    assert b"Positionsauswertung" in response.content
    assert b"Lager-PIN" in response.content
    assert b"Anwesenheitsmappe" in response.content


@pytest.mark.django_db
def test_participant_detail_has_one_current_context_and_section_navigation(client):
    participant = ParticipantFactory()
    participant.arrival_date = date(2026, 6, 1)
    participant.departure_date = date(2026, 6, 8)
    participant.save(update_fields=["arrival_date", "departure_date", "booked_nights"])
    client.force_login(SuperUserFactory())

    response = client.get(reverse("participant-detail", args=[participant.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert content.count('aria-current="page"') == 1
    for section_id in (
        "participant-profile",
        "participant-accounting",
        "participant-bookings",
        "participant-family",
        "participant-snapshots",
        "participant-audit",
    ):
        assert f'id="{section_id}"' in content
        assert f'href="#{section_id}"' in content
    assert "Weitere Aktionen" in content
    assert "Stammdaten und Aufenthalt" in content
    assert "01.06.2026" in content
    assert "08.06.2026" in content


@pytest.mark.django_db
def test_technical_admin_uses_native_theme_and_mobile_controls(client):
    client.force_login(SuperUserFactory())

    dashboard = client.get(reverse("admin:index"))
    changelist = client.get(reverse("admin:billing_participant_changelist"))
    change_form = client.get(reverse("admin:billing_participant_add"))

    assert dashboard.status_code == changelist.status_code == change_form.status_code == 200
    assert b"admin-page-intro" in dashboard.content
    assert b"Fliegerlager-Administration" in dashboard.content
    assert b'class="theme-toggle"' in dashboard.content
    for response in (dashboard, changelist, change_form):
        assert b"admin-redesign.css" in response.content
        assert b"admin-redesign-root" in response.content
        assert b"billing/theme.js" not in response.content
    assert b"admin-mobile-menu-toggle" in changelist.content
