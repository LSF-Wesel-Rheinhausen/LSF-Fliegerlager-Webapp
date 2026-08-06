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


def login_user_key(username: str) -> str:
    """Hash a normalized username without retaining PII in rate-limit records."""
    normalized = username.strip().lower()
    if not normalized:
        return ""
    return salted_hmac(
        "billing.login-rate-limit.username.v1",
        normalized,
        algorithm="sha256",
    ).hexdigest()


def check_login_rate_limit(request: HttpRequest, username: str = "") -> bool:
    """Return True if the client IP and username are allowed to attempt a login."""
    from .models import LoginAttempt

    now = timezone.now()
    cutoff = now.timestamp() - 300  # 5 minutes window
    ip_key = f"ip:{kiosk_client_key(request)}"

    ip_attempt = LoginAttempt.objects.filter(client_key=ip_key).first()
    if ip_attempt:
        recent_ip_failures = _recent_attempts(ip_attempt.failure_timestamps, cutoff=cutoff)
        if len(recent_ip_failures) >= 5:
            return False

    if username:
        user_key_hash = login_user_key(username)
        if user_key_hash:
            user_key = f"user:{user_key_hash}"
            user_attempt = LoginAttempt.objects.filter(client_key=user_key).first()
            if user_attempt:
                recent_user_failures = _recent_attempts(user_attempt.failure_timestamps, cutoff=cutoff)
                if len(recent_user_failures) >= 5:
                    return False

    return True


def consume_login_failure(request: HttpRequest, username: str = "") -> None:
    """Record a failed login attempt for the client IP and targeted username."""
    from .models import LoginAttempt

    now = timezone.now()
    cutoff = now.timestamp() - 300
    LoginAttempt.objects.filter(updated_at__lt=now - timedelta(seconds=300)).delete()

    keys_to_update = [f"ip:{kiosk_client_key(request)}"]
    if username:
        user_key_hash = login_user_key(username)
        if user_key_hash:
            keys_to_update.append(f"user:{user_key_hash}")

    with transaction.atomic():
        for key in keys_to_update:
            attempt_state, _created = LoginAttempt.objects.select_for_update().get_or_create(
                client_key=key,
            )
            recent_failures = _recent_attempts(attempt_state.failure_timestamps, cutoff=cutoff)
            recent_failures.append(now.timestamp())
            attempt_state.failure_timestamps = recent_failures
            attempt_state.save(update_fields=["failure_timestamps", "updated_at"])


def is_login_locked_out(username: str) -> bool:
    """Return True if the specified username is currently locked out by rate limiting."""
    from .models import LoginAttempt

    if not username:
        return False
    user_key_hash = login_user_key(username)
    if not user_key_hash:
        return False
    user_key = f"user:{user_key_hash}"
    user_attempt = LoginAttempt.objects.filter(client_key=user_key).first()
    if user_attempt:
        cutoff = timezone.now().timestamp() - 300
        recent_failures = _recent_attempts(user_attempt.failure_timestamps, cutoff=cutoff)
        return len(recent_failures) >= 5
    return False


def clear_login_rate_limit(username: str = "", request: HttpRequest | None = None) -> None:
    """Clear failed login rate-limit records for a targeted username and optional request IP."""
    from .models import LoginAttempt

    if username:
        user_key_hash = login_user_key(username)
        if user_key_hash:
            user_key = f"user:{user_key_hash}"
            LoginAttempt.objects.filter(client_key=user_key).delete()

    if request:
        ip_key = f"ip:{kiosk_client_key(request)}"
        LoginAttempt.objects.filter(client_key=ip_key).delete()
