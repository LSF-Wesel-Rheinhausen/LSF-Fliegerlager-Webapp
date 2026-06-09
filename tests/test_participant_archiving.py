import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from billing.permissions import ADMIN_GROUP, EDITOR_GROUP
from tests.factories import ChargeFactory, ParticipantFactory, UserFactory


@pytest.mark.django_db
def test_editor_can_edit_participant(client):
    editor = UserFactory()
    editor.groups.add(Group.objects.create(name=EDITOR_GROUP))
    participant = ParticipantFactory(first_name="Alt")
    client.force_login(editor)

    response = client.post(
        reverse("participant-edit", args=[participant.pk]),
        {
            "first_name": "Neu",
            "last_name": participant.last_name,
            "status": participant.status,
            "hilfssatz": participant.hilfssatz,
            "berufssatz": participant.berufssatz,
            "booked_nights": participant.booked_nights,
            "actual_nights": participant.actual_nights,
        },
    )

    participant.refresh_from_db()
    assert response.status_code == 302
    assert participant.first_name == "Neu"


@pytest.mark.django_db
def test_admin_archives_and_restores_participant_without_deleting_financial_data(client):
    admin = UserFactory()
    admin.groups.add(Group.objects.create(name=ADMIN_GROUP))
    participant = ParticipantFactory()
    charge = ChargeFactory(participant=participant)
    client.force_login(admin)

    archive_response = client.post(reverse("participant-archive", args=[participant.pk]))

    participant.refresh_from_db()
    assert archive_response.status_code == 302
    assert participant.archived_at is not None
    assert participant.archived_by == admin
    assert participant.charges.get() == charge

    restore_response = client.post(reverse("participant-restore", args=[participant.pk]))

    participant.refresh_from_db()
    assert restore_response.status_code == 302
    assert participant.archived_at is None
    assert participant.archived_by is None


@pytest.mark.django_db
def test_editor_cannot_archive_participant(client):
    editor = UserFactory()
    editor.groups.add(Group.objects.create(name=EDITOR_GROUP))
    participant = ParticipantFactory()
    client.force_login(editor)

    response = client.post(reverse("participant-archive", args=[participant.pk]))

    participant.refresh_from_db()
    assert response.status_code == 302
    assert participant.archived_at is None


@pytest.mark.django_db
def test_archived_participant_is_removed_from_live_camp_settlement(client):
    admin = UserFactory()
    admin.groups.add(Group.objects.create(name=ADMIN_GROUP))
    participant = ParticipantFactory(archived_at=timezone.now())
    client.force_login(admin)

    response = client.get(reverse("camp-detail", args=[participant.camp_id]))

    assert response.status_code == 200
    assert list(response.context["settlements"]) == []
    assert list(response.context["archived_participants"]) == [participant]
