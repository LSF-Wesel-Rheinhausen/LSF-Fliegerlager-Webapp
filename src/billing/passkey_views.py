import json
import logging
from typing import Any, cast

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from webauthn.helpers.exceptions import WebAuthnException

from .models import PasskeyCredential
from .passkeys import (
    PasskeyCeremonyError,
    begin_passkey_authentication,
    begin_passkey_registration,
    finish_passkey_authentication,
    finish_passkey_registration,
)

MAX_PASSKEY_REQUEST_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


def _require_passkeys_enabled() -> None:
    if not settings.PASSKEY_ENABLED:
        raise Http404


def _json_request_body(request: HttpRequest) -> dict[str, Any]:
    if request.content_type != "application/json" or len(request.body) > MAX_PASSKEY_REQUEST_BYTES:
        raise PasskeyCeremonyError("Invalid request body.")
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PasskeyCeremonyError("Invalid request body.") from exc
    if not isinstance(payload, dict):
        raise PasskeyCeremonyError("Invalid request body.")
    return payload


def _audit_event(
    request: HttpRequest,
    event: str,
    *,
    user_id: int | None = None,
    error: Exception | None = None,
) -> None:
    extra = {
        "event": event,
        "request_id": getattr(request, "csp_nonce", "unavailable"),
        "user_id": user_id,
    }
    if error is not None:
        extra["error_type"] = type(error).__name__
        logger.warning(event, extra=extra)
        return
    logger.info(event, extra=extra)


@login_required
def passkey_management(request: HttpRequest) -> HttpResponse:
    """Render the current user's registered passkeys."""
    _require_passkeys_enabled()
    user = cast(User, request.user)
    credentials = PasskeyCredential.objects.filter(user=user)
    return render(request, "billing/passkey_management.html", {"passkey_credentials": credentials})


@require_POST
def passkey_authentication_options(request: HttpRequest) -> HttpResponse:
    """Return a discoverable-credential authentication challenge."""
    _require_passkeys_enabled()
    return HttpResponse(begin_passkey_authentication(request.session), content_type="application/json")


@login_required
@require_POST
def passkey_registration_options(request: HttpRequest) -> HttpResponse:
    """Return registration options bound to the authenticated user."""
    _require_passkeys_enabled()
    user = cast(User, request.user)
    return HttpResponse(
        begin_passkey_registration(user, request.session),
        content_type="application/json",
    )


@login_required
@require_POST
def passkey_registration_verify(request: HttpRequest) -> JsonResponse:
    """Verify and store a passkey registered by the authenticated user."""
    _require_passkeys_enabled()
    user = cast(User, request.user)
    try:
        payload = _json_request_body(request)
        name = payload.get("name")
        credential_data = payload.get("credential")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise PasskeyCeremonyError("Invalid passkey name.")
        if not isinstance(credential_data, dict):
            raise PasskeyCeremonyError("Invalid credential response.")
        credential = finish_passkey_registration(
            user,
            request.session,
            credential_data,
            name=name.strip(),
        )
    except (IntegrityError, PasskeyCeremonyError, WebAuthnException) as exc:
        _audit_event(request, "passkey_registration_failed", user_id=user.pk, error=exc)
        return JsonResponse({"error": "Passkey konnte nicht registriert werden."}, status=400)
    _audit_event(request, "passkey_registration_succeeded", user_id=user.pk)
    return JsonResponse({"id": credential.pk, "name": credential.name}, status=201)


@require_POST
def passkey_authentication_verify(request: HttpRequest) -> JsonResponse:
    """Verify a passkey assertion and create a Django login session."""
    _require_passkeys_enabled()
    try:
        payload = _json_request_body(request)
        credential_data = payload.get("credential")
        if not isinstance(credential_data, dict):
            raise PasskeyCeremonyError("Invalid credential response.")
        user = finish_passkey_authentication(request.session, credential_data)
    except (PasskeyCeremonyError, WebAuthnException) as exc:
        _audit_event(request, "passkey_authentication_failed", error=exc)
        return JsonResponse({"error": "Anmeldung mit Passkey fehlgeschlagen."}, status=400)

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    _audit_event(request, "passkey_authentication_succeeded", user_id=user.pk)
    requested_redirect = payload.get("next")
    redirect_url = resolve_url(settings.LOGIN_REDIRECT_URL)
    if isinstance(requested_redirect, str) and url_has_allowed_host_and_scheme(
        requested_redirect,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        redirect_url = requested_redirect
    return JsonResponse({"redirect": redirect_url})


@login_required
@require_POST
def passkey_delete(request: HttpRequest, credential_id: int) -> HttpResponse:
    """Delete one passkey owned by the authenticated user."""
    _require_passkeys_enabled()
    user = cast(User, request.user)
    credential = get_object_or_404(PasskeyCredential, pk=credential_id, user=user)
    credential.delete()
    _audit_event(request, "passkey_deleted", user_id=user.pk)
    messages.success(request, "Passkey wurde entfernt.")
    return redirect("passkey-manage")
