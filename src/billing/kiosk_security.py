from datetime import timedelta
from ipaddress import ip_address
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import CampKioskAccess, CampKioskRegistrationAttempt


def kiosk_client_address(request: HttpRequest) -> str:
    """Resolve one client address across an explicitly trusted reverse proxy."""
    remote_address = request.META.get("REMOTE_ADDR", "")
    if not isinstance(remote_address, str):
        remote_address = ""
    if remote_address not in settings.KIOSK_ACCESS_TRUSTED_PROXY_ADDRESSES:
        return remote_address

    forwarded_address = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if not isinstance(forwarded_address, str):
        return remote_address
    try:
        return ip_address(forwarded_address.strip()).compressed
    except ValueError:
        # A trusted proxy must overwrite X-Forwarded-For with exactly one IP.
        return remote_address


def kiosk_client_key(request: HttpRequest) -> str:
    """Hash the resolved client address without retaining network data."""
    return salted_hmac(
        "billing.kiosk-access.client.v1",
        kiosk_client_address(request),
        algorithm="sha256",
    ).hexdigest()


def _recent_attempts(values: Any, *, cutoff: float) -> list[float]:
    """Return well-formed timestamps inside the configured sliding window."""
    if not isinstance(values, list):
        return []
    return [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) >= cutoff
    ]


def consume_kiosk_registration_attempt(request: HttpRequest, access: CampKioskAccess) -> bool:
    """Consume one persistent self-registration attempt for a camp and client.

    Returns:
        ``True`` when the request is inside the configured limit, otherwise
        ``False`` without recording another attempt.
    """
    now = timezone.now()
    window_seconds = settings.KIOSK_REGISTRATION_ATTEMPT_WINDOW
    cutoff = now.timestamp() - window_seconds
    CampKioskRegistrationAttempt.objects.filter(updated_at__lt=now - timedelta(seconds=window_seconds)).delete()

    with transaction.atomic():
        attempt_state, _created = CampKioskRegistrationAttempt.objects.select_for_update().get_or_create(
            access=access,
            client_key=kiosk_client_key(request),
        )
        recent_attempts = _recent_attempts(attempt_state.attempt_timestamps, cutoff=cutoff)
        if len(recent_attempts) >= settings.KIOSK_REGISTRATION_MAX_ATTEMPTS:
            return False

        recent_attempts.append(now.timestamp())
        attempt_state.attempt_timestamps = recent_attempts
        attempt_state.save(update_fields=["attempt_timestamps", "updated_at"])
        return True
