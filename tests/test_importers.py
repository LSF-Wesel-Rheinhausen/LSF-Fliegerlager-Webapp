from io import BytesIO

import pytest
from django.core.exceptions import ValidationError

from billing.importers import preview_participants, save_participants
from billing.models import Participant
from tests.factories import CampFactory


def test_csv_preview_validates_required_fields_and_numbers():
    payload = b"first_name,last_name,actual_nights\nAda,,abc\nGrace,Hopper,3\n"

    rows = preview_participants(BytesIO(payload), "teilnehmer.csv")

    assert rows[0].valid is False
    assert "last_name: Pflichtfeld fehlt" in rows[0].errors
    assert "actual_nights: keine gültige Zahl" in rows[0].errors
    assert rows[1].valid is True
    assert rows[1].data["actual_nights"] == 3


@pytest.mark.django_db
def test_save_participants_upserts_valid_rows():
    camp = CampFactory()
    payload = b"first_name,last_name,email\nAda,Lovelace,ada@example.org\n"
    rows = preview_participants(BytesIO(payload), "teilnehmer.csv")

    save_participants(camp, rows)
    save_participants(camp, rows)

    assert Participant.objects.count() == 1
    assert Participant.objects.get().email == "ada@example.org"


def test_xlsx_preview_rejects_invalid_magic_number():
    with pytest.raises(ValidationError, match="gültiges Excel"):
        preview_participants(BytesIO(b"not-an-xlsx"), "teilnehmer.xlsx")


@pytest.mark.django_db
def test_import_confirm_rejects_invalid_signature(client):
    from django.urls import reverse

    from tests.factories import CampFactory, SuperUserFactory

    user = SuperUserFactory(username="admin", email="admin@example.test")
    camp = CampFactory()
    client.force_login(user)

    response = client.post(
        reverse("participant-import", args=[camp.pk]),
        {
            "confirm": "1",
            "rows": "invalid-signature",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("participant-import", args=[camp.pk])
    assert Participant.objects.filter(first_name="Ada").count() == 0
