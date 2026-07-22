import json

import pytest
from django.templatetags.static import static
from django.urls import reverse

from billing.views import KIOSK_PARTICIPANT_SESSION_KEY
from tests.factories import CampFactory, ParticipantFactory


@pytest.mark.django_db
def test_root_redirects_to_private_kiosk(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response["Location"] == reverse("kiosk-home")


@pytest.mark.django_db
def test_central_kiosk_keeps_central_route_prefix(client):
    response = client.get(reverse("central-kiosk-home"))

    assert response.status_code == 302
    assert response["Location"] == reverse("central-kiosk-login")


@pytest.mark.django_db
def test_private_kiosk_exposes_install_guide_and_apple_touch_icon(client):
    response = client.get(reverse("kiosk-login"))

    assert response.status_code == 200
    assert b"data-pwa-install" in response.content
    assert b"data-pwa-install-dialog" in response.content
    assert b'rel="apple-touch-icon"' in response.content
    assert b"/static/billing/icons/icon-192.png" in response.content


@pytest.mark.django_db
def test_central_kiosk_hides_install_guide(client):
    response = client.get(reverse("central-kiosk-login"))

    assert response.status_code == 200
    assert b"data-pwa-install" not in response.content
    assert b"data-pwa-install-dialog" not in response.content


@pytest.mark.parametrize("path", ["/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/favicon.ico"])
def test_platform_icon_fallbacks_redirect_to_app_icon(client, path):
    response = client.get(path)

    assert response.status_code == 301
    assert response["Location"] == static("billing/icons/icon-192.png")


@pytest.mark.django_db
def test_private_kiosk_login_uses_persistent_session_without_autologout(client, settings):
    participant = ParticipantFactory(camp=CampFactory(is_active=True))
    participant.pin.set_pin("1234")
    participant.pin.save()
    session = client.session
    session["kiosk_mode"] = "central"
    session.set_expiry(120)
    session.save()

    response = client.post(
        reverse("kiosk-login"),
        {"participant": f"participant-{participant.pk}", "pin": "1234"},
        follow=True,
    )

    assert response.status_code == 200
    assert response.context["kiosk_mode"] == "private"
    assert response.context["kiosk_autologout"] is False
    assert client.session.get_expire_at_browser_close() is False
    assert client.session.get_expiry_age() == settings.SESSION_COOKIE_AGE
    assert client.session[KIOSK_PARTICIPANT_SESSION_KEY] == participant.pk


@pytest.mark.django_db
def test_central_kiosk_login_enforces_short_autologout(client):
    participant = ParticipantFactory(camp=CampFactory(is_active=True))
    participant.pin.set_pin("1234")
    participant.pin.save()

    response = client.post(
        reverse("central-kiosk-login"),
        {"participant": f"participant-{participant.pk}", "pin": "1234"},
        follow=True,
    )

    assert response.status_code == 200
    assert response.context["kiosk_mode"] == "central"
    assert response.context["kiosk_autologout"] is True
    assert reverse("central-kiosk-logout").encode() in response.content
    assert client.session.get_expiry_age() == 120


@pytest.mark.django_db
def test_switching_kiosk_modes_clears_participant_session(client):
    participant = ParticipantFactory(camp=CampFactory(is_active=True))
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session["kiosk_mode"] = "private"
    session.save()

    response = client.get(reverse("central-kiosk-home"))

    assert response.status_code == 302
    assert response["Location"] == reverse("central-kiosk-login")
    assert KIOSK_PARTICIPANT_SESSION_KEY not in client.session


@pytest.mark.parametrize(
    ("route_name", "expected_scope", "expected_start"),
    [
        ("pwa-manifest-admin", "/", "/camps/"),
        ("pwa-manifest-kiosk", "/kiosk/", "/kiosk/"),
        ("pwa-manifest-central", "/central/kiosk/", "/central/kiosk/"),
    ],
)
def test_pwa_manifests_are_surface_specific(client, route_name, expected_scope, expected_start):
    response = client.get(reverse(route_name))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/manifest+json")
    manifest = json.loads(response.content)
    assert manifest["scope"] == expected_scope
    assert manifest["start_url"] == expected_start
    assert {icon["sizes"] for icon in manifest["icons"]} >= {"192x192", "512x512"}
    assert next(icon for icon in manifest["icons"] if icon["sizes"] == "192x192")["purpose"] == "any"


@pytest.mark.parametrize(
    ("route_name", "expected_scope", "expected_cache_name"),
    [
        ("pwa-worker-admin", "/", "fliegerlager-admin-v3"),
        ("pwa-worker-kiosk", "/kiosk/", "fliegerlager-kiosk-v3"),
        ("pwa-worker-central", "/central/kiosk/", "fliegerlager-central-v3"),
    ],
)
def test_service_workers_have_explicit_scopes(client, route_name, expected_scope, expected_cache_name):
    response = client.get(reverse(route_name))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/javascript")
    assert response["Service-Worker-Allowed"] == expected_scope
    assert response["Cache-Control"] == "no-cache"
    javascript = response.content.decode().replace("\\u002D", "-")
    assert expected_cache_name in javascript
    assert b"offline" in response.content
    assert b'request.method !== "GET"' in response.content


def test_offline_page_contains_no_business_data(client):
    response = client.get(reverse("pwa-offline"))

    assert response.status_code == 200
    assert b"Du bist offline" in response.content
    assert b"participant" not in response.content.lower()


@pytest.mark.django_db
def test_security_policy_allows_same_origin_manifests_and_workers(client):
    response = client.get(reverse("kiosk-login"))

    policy = response["Content-Security-Policy"]
    assert "manifest-src 'self'" in policy
    assert "worker-src 'self'" in policy
