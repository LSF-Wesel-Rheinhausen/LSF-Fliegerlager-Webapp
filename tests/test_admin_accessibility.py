from html.parser import HTMLParser

import pytest
from django.urls import reverse

from tests.factories import ParticipantFactory, SuperUserFactory


class _AccessibilityReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.references: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if element_id := attributes.get("id"):
            self.ids.append(element_id)
        for attribute in ("aria-describedby", "aria-labelledby"):
            for reference in (attributes.get(attribute) or "").split():
                self.references.append((attribute, reference))


def _parse_accessibility_references(response_content: bytes) -> _AccessibilityReferenceParser:
    parser = _AccessibilityReferenceParser()
    parser.feed(response_content.decode())
    return parser


@pytest.mark.django_db
@pytest.mark.parametrize("form_url_kind", ["add", "change"])
def test_participant_admin_has_only_existing_accessibility_references(client, form_url_kind):
    admin = SuperUserFactory()
    participant = ParticipantFactory()
    client.force_login(admin)
    url = reverse(
        f"admin:billing_participant_{form_url_kind}",
        args=[participant.pk] if form_url_kind == "change" else None,
    )

    response = client.get(url)

    assert response.status_code == 200
    parser = _parse_accessibility_references(response.content)
    assert len(parser.ids) == len(set(parser.ids))
    missing_references = [reference for _attribute, reference in parser.references if reference not in parser.ids]
    assert not missing_references, missing_references
    assert {"id_arrival_date", "id_departure_date", "id_archived_at_0", "id_archived_at_1"} <= set(parser.ids)
    assert "id_arrival_date_timezone_warning_helptext" not in parser.ids
    assert "id_departure_date_timezone_warning_helptext" not in parser.ids
    assert "id_archived_at_timezone_warning_helptext" not in parser.ids


@pytest.mark.django_db
def test_participant_admin_keeps_model_helptext_connected(client):
    admin = SuperUserFactory()
    participant = ParticipantFactory()
    client.force_login(admin)

    response = client.get(reverse("admin:billing_participant_change", args=[participant.pk]))

    parser = _parse_accessibility_references(response.content)
    assert "id_hilfssatz_helptext" in parser.ids
    assert ("aria-describedby", "id_hilfssatz_helptext") in parser.references
