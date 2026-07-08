import pytest
from django.conf import settings
from django.urls import reverse


@pytest.mark.django_db
def test_common_security_headers_are_set(client):
    response = client.get(reverse("kiosk-login"))

    assert response.status_code == 200
    assert response["Content-Security-Policy"] == (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    assert response["Cross-Origin-Embedder-Policy"] == "require-corp"
    assert response["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response["Cross-Origin-Resource-Policy"] == "same-origin"
    assert response["Permissions-Policy"] == "camera=(), geolocation=(), microphone=(), payment=()"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_security_headers_middleware_wraps_static_file_middleware():
    security_headers_index = settings.MIDDLEWARE.index("config.middleware.SecurityHeadersMiddleware")
    whitenoise_index = settings.MIDDLEWARE.index("whitenoise.middleware.WhiteNoiseMiddleware")

    assert security_headers_index < whitenoise_index
