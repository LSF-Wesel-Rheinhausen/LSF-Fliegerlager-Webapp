import pytest
from django.conf import settings
from django.urls import reverse


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


def test_security_headers_middleware_wraps_static_file_middleware():
    security_headers_index = settings.MIDDLEWARE.index("config.middleware.SecurityHeadersMiddleware")
    whitenoise_index = settings.MIDDLEWARE.index("whitenoise.middleware.WhiteNoiseMiddleware")

    assert security_headers_index < whitenoise_index
