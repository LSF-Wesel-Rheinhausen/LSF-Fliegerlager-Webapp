from datetime import timedelta
from typing import Literal, cast
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import CampKioskAccessAdminForm, KioskCampAccessForm
from .kiosk_access import (
    KIOSK_ACCESS_COOKIE_NAME,
    PUBLIC_KIOSK_ROUTES,
    clear_kiosk_access_cookie,
    clear_kiosk_identity_session,
    kiosk_access_from_request,
    set_kiosk_access_cookie,
)
from .models import Camp, CampKioskAccess, CampKioskAccessAttempt
from .permissions import admin_required
from .views import _kiosk_context

PinAttemptResult = Literal["accepted", "rejected", "blocked"]


def _kiosk_client_key(request: HttpRequest) -> str:
    """Hash the server-observed peer address without retaining network data."""
    remote_address = request.META.get("REMOTE_ADDR", "")
    if not isinstance(remote_address, str):
        remote_address = ""
    return salted_hmac(
        "billing.kiosk-access.client.v1",
        remote_address,
        algorithm="sha256",
    ).hexdigest()


def _check_pin_with_server_throttle(
    request: HttpRequest,
    access: CampKioskAccess,
    raw_pin: str | None,
) -> PinAttemptResult:
    """Validate one PIN attempt while serializing its server-side failure state."""
    now = timezone.now()
    cutoff = now.timestamp() - settings.KIOSK_ACCESS_ATTEMPT_WINDOW
    CampKioskAccessAttempt.objects.filter(
        updated_at__lt=now - timedelta(seconds=settings.KIOSK_ACCESS_ATTEMPT_WINDOW)
    ).delete()

    with transaction.atomic():
        attempt_state, _created = CampKioskAccessAttempt.objects.select_for_update().get_or_create(
            access=access,
            client_key=_kiosk_client_key(request),
        )
        stored_values = attempt_state.failure_timestamps
        if not isinstance(stored_values, list):
            stored_values = []
        recent_failures = [
            float(value)
            for value in stored_values
            if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) >= cutoff
        ]
        if len(recent_failures) >= settings.KIOSK_ACCESS_MAX_ATTEMPTS:
            return "blocked"
        if raw_pin is not None and access.check_pin(raw_pin):
            attempt_state.delete()
            return "accepted"

        recent_failures.append(now.timestamp())
        attempt_state.failure_timestamps = recent_failures
        attempt_state.save(update_fields=["failure_timestamps", "updated_at"])
        if len(recent_failures) >= settings.KIOSK_ACCESS_MAX_ATTEMPTS:
            return "blocked"
        return "rejected"


def _rate_limited_response(
    request: HttpRequest,
    form: KioskCampAccessForm,
    context: dict[str, object],
) -> HttpResponse:
    form.add_error(None, "Zu viele Fehlversuche. Bitte versuche es in fünf Minuten erneut.")
    response = render(
        request,
        "billing/kiosk_access.html",
        {
            "form": form,
            **context,
        },
        status=429,
    )
    response["Retry-After"] = str(settings.KIOSK_ACCESS_ATTEMPT_WINDOW)
    if KIOSK_ACCESS_COOKIE_NAME in request.COOKIES:
        clear_kiosk_access_cookie(response)
    return response


def _safe_kiosk_next_url(request: HttpRequest, kiosk_mode: str) -> str:
    default_route = "central-kiosk-home" if kiosk_mode == "central" else "kiosk-home"
    default_url = reverse(default_route)
    requested_url = request.GET.get("next", "")
    requested_path = urlsplit(requested_url).path
    try:
        route_name = resolve(requested_path).url_name
    except Resolver404:
        route_name = None
    expected_prefix = "central-kiosk-" if kiosk_mode == "central" else "kiosk-"
    is_allowed_path = bool(
        route_name
        and route_name not in PUBLIC_KIOSK_ROUTES
        and (
            route_name.startswith(expected_prefix)
            or (kiosk_mode == "private" and route_name in {"kiosk-root", "user-guide"})
        )
    )
    if (
        requested_url
        and url_has_allowed_host_and_scheme(
            requested_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
        and is_allowed_path
    ):
        return requested_url
    return default_url


def kiosk_access_prompt(request: HttpRequest, kiosk_mode: str) -> HttpResponse:
    """Render the shared camp PIN prompt for one kiosk device mode."""
    if kiosk_access_from_request(request) is not None:
        return redirect(_safe_kiosk_next_url(request, kiosk_mode))
    clear_kiosk_identity_session(request)

    form = KioskCampAccessForm(request.POST or None)
    access = CampKioskAccess.objects.select_related("camp").filter(camp__is_active=True).exclude(pin_hash="").first()
    context = _kiosk_context(kiosk_mode)
    context["kiosk_autologout"] = False
    context["kiosk_access_prompt"] = True
    if access is None:
        response = render(
            request,
            "billing/kiosk_access.html",
            {
                "access_unavailable": True,
                **context,
            },
            status=503,
        )
        if KIOSK_ACCESS_COOKIE_NAME in request.COOKIES:
            clear_kiosk_access_cookie(response)
        return response

    if request.method == "POST":
        form_is_valid = form.is_valid()
        attempt_result = _check_pin_with_server_throttle(
            request,
            access,
            form.cleaned_data["pin"] if form_is_valid else None,
        )
        if attempt_result == "accepted":
            response = redirect(_safe_kiosk_next_url(request, kiosk_mode))
            set_kiosk_access_cookie(response, access)
            return response
        if attempt_result == "blocked":
            return _rate_limited_response(request, form, context)
        if form_is_valid:
            form.add_error("pin", "Lager-PIN ist ungültig.")

    response = render(
        request,
        "billing/kiosk_access.html",
        {
            "form": form,
            **context,
        },
    )
    if KIOSK_ACCESS_COOKIE_NAME in request.COOKIES:
        clear_kiosk_access_cookie(response)
    return response


@admin_required
def camp_kiosk_access_settings(request: HttpRequest, camp_id: int) -> HttpResponse:
    """Configure the shared kiosk PIN for one camp."""
    camp = get_object_or_404(Camp, pk=camp_id)
    form = CampKioskAccessAdminForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            access, _created = CampKioskAccess.objects.select_for_update().get_or_create(camp=camp)
            access.set_pin(form.cleaned_data["pin"], changed_by=cast(User, request.user))
            access.save()
        messages.success(request, "Lager-PIN gespeichert. Alle bisherigen Lagerzugänge wurden widerrufen.")
        return redirect("camp-kiosk-access-settings", camp_id=camp.pk)

    configured_access = CampKioskAccess.objects.filter(camp=camp).exclude(pin_hash="").first()
    return render(
        request,
        "billing/camp_kiosk_access.html",
        {
            "camp": camp,
            "form": form,
            "is_configured": configured_access is not None,
            "rotated_at": configured_access.rotated_at if configured_access is not None else None,
        },
    )


@admin_required
@require_POST
def camp_kiosk_access_revoke(request: HttpRequest, camp_id: int) -> HttpResponse:
    """Invalidate every kiosk access cookie previously issued for one camp."""
    camp = get_object_or_404(Camp, pk=camp_id)
    with transaction.atomic():
        access = CampKioskAccess.objects.select_for_update().filter(camp=camp).exclude(pin_hash="").first()
        if access is not None:
            access.revoke_all(changed_by=cast(User, request.user))
            access.save()
    if access is None:
        messages.warning(request, "Für dieses Lager ist noch keine Lager-PIN eingerichtet.")
    else:
        messages.success(request, "Alle bestehenden Lagerzugänge wurden zentral widerrufen.")
    return redirect("camp-kiosk-access-settings", camp_id=camp.pk)
