from typing import Any

import pytest
from django.http import HttpResponse
from django.test import Client

from billing.kiosk_access import KIOSK_ACCESS_COOKIE_NAME, set_kiosk_access_cookie
from billing.models import Camp, CampKioskAccess


class AuthorizedKioskClient(Client):
    """Test client that satisfies the shared camp gate before kiosk requests."""

    def _authorize_active_camp(self) -> None:
        camp = Camp.objects.filter(is_active=True).first()
        if camp is None:
            camp = Camp.objects.create(name="Kiosk-Testlager", year=2099)
        access, _created = CampKioskAccess.objects.get_or_create(camp=camp)
        if not access.pin_hash:
            access.set_pin("246810")
            access.save()
        cookie_response = HttpResponse()
        set_kiosk_access_cookie(cookie_response, access)
        self.cookies[KIOSK_ACCESS_COOKIE_NAME] = cookie_response.cookies[KIOSK_ACCESS_COOKIE_NAME].value

    def request(self, **request: Any) -> HttpResponse:
        self._authorize_active_camp()
        return super().request(**request)


@pytest.fixture
def kiosk_client() -> AuthorizedKioskClient:
    """Return a client authorized for the active camp's first kiosk gate."""
    return AuthorizedKioskClient()


@pytest.fixture(autouse=True)
def configure_test_push_origins(settings: Any) -> None:
    """Allow only deterministic test push origins unless a test overrides them."""
    settings.WEB_PUSH_ALLOWED_ORIGINS = ("https://push.example.test", "https://example.com")
