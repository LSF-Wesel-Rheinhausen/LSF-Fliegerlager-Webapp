from unittest.mock import patch

from django.db import OperationalError
from django.test import override_settings
from django.urls import reverse

from tests.factories import UserFactory


def test_healthcheck_reports_ready(client, db):
    response = client.get(reverse("healthcheck"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthcheck_reports_database_failure_without_details(client):
    with patch("config.views.connection.cursor", side_effect=OperationalError("secret database detail")):
        response = client.get(reverse("healthcheck"))

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert b"secret" not in response.content


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
def test_unknown_url_renders_custom_not_found_page(client):
    response = client.get("/diese-url-gibt-es-nicht/")

    assert response.status_code == 404
    assert b"Seite nicht gefunden" in response.content
    assert b"Die angeforderte Adresse existiert nicht" in response.content
    assert b"Using the URLconf defined in" not in response.content
    assert f'href="{reverse("kiosk-home")}"'.encode() in response.content
    assert b">Zum Kiosk<" in response.content
    assert b">Zur \xc3\x9cbersicht<" not in response.content


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"])
def test_unknown_url_renders_custom_not_found_page_in_debug_mode(client):
    response = client.get("/auch-im-debug-modus-unbekannt/")

    assert response.status_code == 404
    assert b"Seite nicht gefunden" in response.content
    assert b"Using the URLconf defined in" not in response.content


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
def test_unknown_url_links_authenticated_users_to_overview(client, db):
    client.force_login(UserFactory())

    response = client.get("/angemeldet-aber-unbekannt/")

    assert response.status_code == 404
    assert f'href="{reverse("camp-list")}"'.encode() in response.content
    assert b">Zur \xc3\x9cbersicht<" in response.content
    assert b">Zum Kiosk<" not in response.content
