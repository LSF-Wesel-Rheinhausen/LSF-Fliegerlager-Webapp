import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.cache import patch_cache_control, patch_vary_headers

from .models import CampKioskAccess
from .permissions import is_editor

KIOSK_ACCESS_COOKIE_NAME = "fliegerlager_kiosk_access"
KIOSK_ACCESS_SIGNING_SALT = "billing.kiosk-access.v1"
KIOSK_PARTICIPANT_SESSION_KEY = "kiosk_participant_id"
KIOSK_FAMILY_MEMBER_SESSION_KEY = "kiosk_family_member_id"
KIOSK_PIN_SETUP_SESSION_KEY = "kiosk_pin_setup_participant_id"
KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY = "kiosk_pin_setup_family_member_id"
KIOSK_MODE_SESSION_KEY = "kiosk_mode"
KIOSK_IDENTITY_SESSION_KEYS = (
    KIOSK_PARTICIPANT_SESSION_KEY,
    KIOSK_FAMILY_MEMBER_SESSION_KEY,
    KIOSK_PIN_SETUP_SESSION_KEY,
    KIOSK_PIN_SETUP_FAMILY_MEMBER_SESSION_KEY,
)
PUBLIC_KIOSK_ROUTES = frozenset(
    {
        "pwa-manifest-kiosk",
        "pwa-worker-kiosk",
        "pwa-manifest-central",
        "pwa-worker-central",
        "kiosk-access",
        "central-kiosk-access",
    }
)
KIOSK_ACCESS_PROMPT_ROUTES = frozenset({"kiosk-access", "central-kiosk-access"})


def _signed_access_value(access: CampKioskAccess) -> str:
    """Return a timestamped token containing no PIN or participant data."""
    return signing.dumps(
        {"camp_id": access.camp_id, "generation": str(access.generation)},
        salt=KIOSK_ACCESS_SIGNING_SALT,
        compress=True,
    )


def set_kiosk_access_cookie(response: HttpResponse, access: CampKioskAccess) -> None:
    """Attach the hardened persistent kiosk access cookie to response."""
    response.set_cookie(
        KIOSK_ACCESS_COOKIE_NAME,
        _signed_access_value(access),
        max_age=settings.KIOSK_ACCESS_COOKIE_AGE,
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
        path="/",
    )


def clear_kiosk_access_cookie(response: HttpResponse) -> None:
    """Expire the kiosk access cookie on the current browser."""
    response.delete_cookie(KIOSK_ACCESS_COOKIE_NAME, path="/", samesite="Lax")


def clear_kiosk_identity_session(request: HttpRequest) -> None:
    """Remove participant identity and PIN-setup state from a kiosk session."""
    for key in KIOSK_IDENTITY_SESSION_KEYS:
        request.session.pop(key, None)


def _valid_payload(value: str) -> dict[str, Any] | None:
    try:
        payload = signing.loads(
            value,
            salt=KIOSK_ACCESS_SIGNING_SALT,
            max_age=settings.KIOSK_ACCESS_COOKIE_AGE,
        )
    except signing.BadSignature:
        return None
    if not isinstance(payload, dict):
        return None
    camp_id = payload.get("camp_id")
    generation = payload.get("generation")
    if not isinstance(camp_id, int) or isinstance(camp_id, bool) or not isinstance(generation, str):
        return None
    try:
        uuid.UUID(generation)
    except ValueError:
        return None
    return payload


def kiosk_access_from_request(request: HttpRequest) -> CampKioskAccess | None:
    """Return the active access record represented by request's cookie."""
    value = request.COOKIES.get(KIOSK_ACCESS_COOKIE_NAME)
    if not value:
        return None
    payload = _valid_payload(value)
    if payload is None:
        return None
    return (
        CampKioskAccess.objects.select_related("camp")
        .filter(
            camp_id=payload["camp_id"],
            camp__is_active=True,
            generation=payload["generation"],
        )
        .exclude(pin_hash="")
        .first()
    )


def _is_protected_kiosk_route(route_name: str | None) -> bool:
    if not route_name or route_name in PUBLIC_KIOSK_ROUTES:
        return False
    return route_name in {"kiosk-root", "user-guide"} or route_name.startswith(("kiosk-", "central-kiosk-"))


class KioskAccessMiddleware:
    """Require a valid camp access cookie before resolving kiosk pages."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if getattr(request, "_kiosk_access_response_private", False):
            patch_cache_control(response, no_store=True, private=True)
            patch_vary_headers(response, ("Cookie",))
        return response

    def process_view(
        self,
        request: HttpRequest,
        _view_func: Callable[..., HttpResponse],
        _view_args: tuple[Any, ...],
        _view_kwargs: dict[str, Any],
    ) -> HttpResponse | None:
        route_name = request.resolver_match.url_name if request.resolver_match else None
        protects_kiosk_route = _is_protected_kiosk_route(route_name)
        protects_kiosk_receipt = route_name == "expense-receipt" and not is_editor(request.user)
        if protects_kiosk_route or protects_kiosk_receipt or route_name in KIOSK_ACCESS_PROMPT_ROUTES:
            request._kiosk_access_response_private = True  # type: ignore[attr-defined]
        if not protects_kiosk_route and not protects_kiosk_receipt:
            return None
        access = kiosk_access_from_request(request)
        if access is not None:
            request.kiosk_access = access  # type: ignore[attr-defined]
            return None
        clear_kiosk_identity_session(request)
        response: HttpResponse
        if request.method in {"GET", "HEAD"} and not protects_kiosk_receipt:
            access_path = (
                "/central/kiosk/access/" if (route_name or "").startswith("central-kiosk-") else "/kiosk/access/"
            )
            response = redirect(f"{access_path}?{urlencode({'next': request.get_full_path()})}")
        else:
            response = HttpResponse("Gültiger Lagerzugang erforderlich.", status=403)
        clear_kiosk_access_cookie(response)
        return response
