from html.parser import HTMLParser

import pytest
from django.urls import reverse

from billing.views import KIOSK_PARTICIPANT_SESSION_KEY
from tests.factories import CampFactory, ParticipantFactory, SuperUserFactory


class _HeadingAndNavParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.h1_texts: list[str] = []
        self.skip_links: list[dict[str, str]] = []
        self.main_elements: list[dict[str, str]] = []
        self.aria_current_links: list[dict[str, str]] = []
        self._current_tag: str | None = None
        self._current_text_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "a" and "skip-link" in (attr_dict.get("class") or ""):
            self.skip_links.append(attr_dict)
        if tag == "main":
            self.main_elements.append(attr_dict)
        if tag == "a" and attr_dict.get("aria-current") == "page":
            self.aria_current_links.append(attr_dict)
        if tag == "h1":
            self._current_tag = "h1"
            self._current_text_buffer = []

    def handle_data(self, data: str) -> None:
        if self._current_tag == "h1":
            self._current_text_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._current_tag == "h1":
            self.h1_texts.append("".join(self._current_text_buffer).strip())
            self._current_tag = None


@pytest.mark.django_db
def test_admin_pages_contain_skip_link_and_main_target(client):
    admin = SuperUserFactory()
    client.force_login(admin)

    response = client.get(reverse("admin-guide"))

    assert response.status_code == 200
    parser = _HeadingAndNavParser()
    parser.feed(response.content.decode("utf-8"))

    assert len(parser.skip_links) == 1
    assert parser.skip_links[0].get("href") == "#main-content"
    assert len(parser.main_elements) == 1
    assert parser.main_elements[0].get("id") == "main-content"
    assert parser.main_elements[0].get("tabindex") == "-1"
    assert len(parser.aria_current_links) >= 1
    assert any(link.get("href") == reverse("admin-guide") for link in parser.aria_current_links)


@pytest.mark.django_db
def test_kiosk_login_pre_camp_has_single_h1_and_skip_link(kiosk_client):
    CampFactory(is_active=True, starts_on="2030-07-01", ends_on="2030-07-14")

    response = kiosk_client.get(reverse("kiosk-login"))

    assert response.status_code == 200
    parser = _HeadingAndNavParser()
    parser.feed(response.content.decode("utf-8"))

    assert len(parser.skip_links) == 1
    assert parser.skip_links[0].get("href") == "#main-content"
    assert len(parser.main_elements) == 1
    assert parser.main_elements[0].get("id") == "main-content"
    assert parser.h1_texts == ["Kiosk"]
    assert b'id="wizard-step-announcer"' in response.content
    assert b'tabindex="-1"' in response.content


@pytest.mark.django_db
def test_kiosk_home_mobile_nav_has_aria_current(kiosk_client):
    participant = ParticipantFactory(camp=CampFactory(is_active=True))
    session = kiosk_client.session
    session["kiosk_mode"] = "private"
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    parser = _HeadingAndNavParser()
    parser.feed(response.content.decode("utf-8"))

    assert len(parser.aria_current_links) >= 1
    assert any(link.get("href") == reverse("kiosk-home") for link in parser.aria_current_links)
