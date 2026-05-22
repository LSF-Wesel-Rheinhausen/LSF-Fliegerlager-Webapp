from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from tests.factories import CampFactory

from billing.importers import preview_participants, save_participants
from billing.models import OvernightCategory, Participant


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
    assert OvernightCategory.objects.filter(camp=camp, name="Bestand").exists() is True


def test_xlsx_preview_rejects_invalid_magic_number():
    with pytest.raises(ValidationError, match="gültiges Excel"):
        preview_participants(BytesIO(b"not-an-xlsx"), "teilnehmer.xlsx")
