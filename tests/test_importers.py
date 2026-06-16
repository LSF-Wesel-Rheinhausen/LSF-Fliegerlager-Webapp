from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from billing.forms import ParticipantImportForm
from billing.importers import preview_participants, save_participants
from billing.models import Participant
from tests.factories import CampFactory, ParticipantFactory


def test_csv_preview_validates_required_fields_and_numbers():
    payload = (
        b"Vorname,Nachname,Anreise,Abreise,Hilfssatz,Berufssatz,ist_n\xc3\xa4chte\n"
        b"Ada,,01.08.2026,10.08.2026,1.0,1.0,abc\n"
        b"Grace,Hopper,01.08.2026,10.08.2026,1.0,1.0,3\n"
    )

    rows = preview_participants(BytesIO(payload), "teilnehmer.csv")

    assert rows[0].valid is False
    assert "Nachname: Pflichtfeld fehlt" in rows[0].errors
    assert "actual_nights: keine gültige Zahl" in rows[0].errors
    
    assert rows[1].valid is True
    assert rows[1].data["actual_nights"] == 3


def test_csv_preview_validates_dates_and_rates():
    payload = (
        b"Vorname,Nachname,Anreise,Abreise,Hilfssatz,Berufssatz\n"
        b"Invalid,Date,99.99.2026,10.08.2026,1.0,1.0\n"
        b"Invalid,Rate,01.08.2026,10.08.2026,1.5,-0.1\n"
        b"Valid,Person,01.08.2026,10.08.2026,1.0,1.0\n"
    )

    rows = preview_participants(BytesIO(payload), "teilnehmer.csv")

    assert rows[0].valid is False
    assert "Anreise: ungültiges Datumsformat" in rows[0].errors[0]
    
    assert rows[1].valid is False
    assert "Hilfssatz: Wert muss zwischen 0 und 1 liegen" in rows[1].errors
    assert "Berufssatz: Wert muss zwischen 0 und 1 liegen" in rows[1].errors
    
    assert rows[2].valid is True


def test_csv_preview_parses_optional_and_unknown_fields():
    payload = (
        b"Vorname,Nachname,Anreise,Abreise,Hilfssatz,Berufssatz,Telefon,Kind,Lieblingsessen,Verein\n"
        b"Max,Mustermann,01.08.2026,10.08.2026,1.0,1.0,01234,Ja,Pizza,LSV\n"
    )

    rows = preview_participants(BytesIO(payload), "teilnehmer.csv")

    assert rows[0].valid is True
    assert rows[0].data["first_name"] == "Max"
    assert rows[0].data["phone"] == "01234"
    assert rows[0].data["is_child"] is True
    # Unknown fields should be joined into notes
    assert "Lieblingsessen: Pizza" in rows[0].data["notes"]
    assert "Verein: LSV" in rows[0].data["notes"]


@pytest.mark.django_db
def test_save_participants_upserts_valid_rows():
    camp = CampFactory()
    payload = (
        b"Vorname,Nachname,Anreise,Abreise,Hilfssatz,Berufssatz,Email\n"
        b"Ada,Lovelace,01.08.2026,10.08.2026,1.0,1.0,ada@example.org\n"
    )
    rows = preview_participants(BytesIO(payload), "teilnehmer.csv")

    save_participants(camp, rows)
    save_participants(camp, rows)

    assert Participant.objects.count() == 1
    assert Participant.objects.get().email == "ada@example.org"


@pytest.mark.django_db
def test_participant_save_calculates_booked_nights():
    camp = CampFactory()
    import datetime
    participant = ParticipantFactory(
        camp=camp, 
        arrival_date=datetime.date(2026, 8, 1), 
        departure_date=datetime.date(2026, 8, 10),
        booked_nights=0
    )
    assert participant.booked_nights == 9


@pytest.mark.django_db
def test_save_participants_rejects_archived_name_conflict():
    camp = CampFactory()
    ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace", archived_at="2026-06-09T12:00:00Z")
    payload = (
        b"Vorname,Nachname,Anreise,Abreise,Hilfssatz,Berufssatz\n"
        b"Ada,Lovelace,01.08.2026,10.08.2026,1.0,1.0\n"
    )
    rows = preview_participants(BytesIO(payload), "teilnehmer.csv")

    with pytest.raises(ValidationError, match="archiviert"):
        save_participants(camp, rows)


def test_xlsx_preview_rejects_invalid_magic_number():
    with pytest.raises(ValidationError, match="gültiges Excel"):
        preview_participants(BytesIO(b"not-an-xlsx"), "teilnehmer.xlsx")


def test_csv_preview_rejects_non_utf8_content():
    with pytest.raises(ValidationError, match="UTF-8"):
        preview_participants(BytesIO(b"first_name,last_name\n\xff,Test\n"), "teilnehmer.csv")


def test_participant_import_form_rejects_unsupported_extension_and_large_files():
    unsupported = ParticipantImportForm(files={"file": SimpleUploadedFile("participants.txt", b"data")})
    oversized = ParticipantImportForm(
        files={"file": SimpleUploadedFile("participants.csv", b"x" * (5 * 1024 * 1024 + 1))}
    )

    assert unsupported.is_valid() is False
    assert oversized.is_valid() is False
    assert "file" in unsupported.errors
    assert "file" in oversized.errors


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
