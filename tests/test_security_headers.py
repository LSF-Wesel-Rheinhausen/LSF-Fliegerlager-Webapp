import re

import pytest
from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import reverse
from whitenoise.middleware import WhiteNoiseMiddleware

from config.middleware import SecurityHeadersMiddleware
from tests.factories import UserFactory


@pytest.mark.django_db
def test_common_security_headers_are_set(client):
    response = client.get(reverse("kiosk-login"))
    csp = response["Content-Security-Policy"]

    assert response.status_code == 200
    assert "default-src 'self'" in csp
    assert "script-src 'self' 'nonce-" in csp
    assert "style-src 'self' 'nonce-" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp
    assert "style-src 'self' 'unsafe-inline'" not in csp
    assert "script-src-attr 'unsafe-inline'" in csp
    assert "style-src-attr 'unsafe-inline'" in csp
    assert response["Cross-Origin-Embedder-Policy"] == "require-corp"
    assert response["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response["Cross-Origin-Resource-Policy"] == "same-origin"
    assert response["Permissions-Policy"] == "camera=(), geolocation=(), microphone=(), payment=()"
    assert response["X-Content-Type-Options"] == "nosniff"


@pytest.mark.django_db
def test_base_template_inline_script_uses_the_response_csp_nonce(client):
    UserFactory()

    response = client.get(reverse("login"))
    nonce_match = re.search(r"script-src 'self' 'nonce-([^']+)'", response["Content-Security-Policy"])

    assert nonce_match is not None
    assert f'<script nonce="{nonce_match.group(1)}">'.encode() in response.content


def test_security_headers_middleware_wraps_static_file_middleware():
    security_headers_index = settings.MIDDLEWARE.index("config.middleware.SecurityHeadersMiddleware")
    whitenoise_index = settings.MIDDLEWARE.index("whitenoise.middleware.WhiteNoiseMiddleware")

    assert security_headers_index < whitenoise_index


def test_whitenoise_does_not_add_wildcard_cors_header():
    assert settings.WHITENOISE_ALLOW_ALL_ORIGINS is False


@override_settings(DEBUG=False)
@pytest.mark.django_db
def test_static_responses_keep_same_origin_protection(tmp_path):
    static_file = tmp_path / "billing" / "app.css"
    static_file.parent.mkdir(parents=True)
    static_file.write_text("body { color: black; }", encoding="utf-8")

    with override_settings(STATIC_ROOT=tmp_path):
        static_handler = WhiteNoiseMiddleware(lambda request: HttpResponse(status=404))
        middleware = SecurityHeadersMiddleware(static_handler)
        response = middleware(RequestFactory().get("/static/billing/app.css"))

    try:
        assert response.status_code == 200
        assert "Access-Control-Allow-Origin" not in response
        assert response["Cross-Origin-Resource-Policy"] == "same-origin"
        assert response["Cross-Origin-Embedder-Policy"] == "require-corp"
        assert response["Cross-Origin-Opener-Policy"] == "same-origin"
    finally:
        response.close()
