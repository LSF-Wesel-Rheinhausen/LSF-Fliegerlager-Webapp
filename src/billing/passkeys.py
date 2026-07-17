import time
from collections.abc import MutableMapping
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .models import PasskeyCredential

REGISTRATION_CHALLENGE_SESSION_KEY = "passkey_registration_challenge"
AUTHENTICATION_CHALLENGE_SESSION_KEY = "passkey_authentication_challenge"
ALLOWED_TRANSPORTS = {"ble", "hybrid", "internal", "nfc", "smart-card", "usb"}


class PasskeyCeremonyError(ValueError):
    """Indicate that a WebAuthn ceremony cannot be completed safely."""


def _require_passkey_settings() -> tuple[str, str, str]:
    """Return validated relying-party settings for a WebAuthn ceremony."""
    if not settings.PASSKEY_ENABLED:
        raise ImproperlyConfigured("Passkey authentication is disabled.")
    if not settings.PASSKEY_RP_ID or not settings.PASSKEY_RP_NAME or not settings.PASSKEY_ORIGIN:
        raise ImproperlyConfigured("PASSKEY_RP_ID, PASSKEY_RP_NAME and PASSKEY_ORIGIN are required.")
    rp_id = settings.PASSKEY_RP_ID
    origin = settings.PASSKEY_ORIGIN
    rp_parts = urlsplit(f"//{rp_id}")
    if rp_parts.hostname != rp_id.lower() or rp_parts.port is not None:
        raise ImproperlyConfigured("PASSKEY_RP_ID must be a hostname without scheme, port or path.")
    origin_parts = urlsplit(origin)
    if origin_parts.path or origin_parts.query or origin_parts.fragment or not origin_parts.hostname:
        raise ImproperlyConfigured("PASSKEY_ORIGIN must be an exact origin without path, query or fragment.")
    if origin_parts.username is not None or origin_parts.password is not None:
        raise ImproperlyConfigured("PASSKEY_ORIGIN must not contain embedded credentials.")
    try:
        origin_port = origin_parts.port
    except ValueError as exc:
        raise ImproperlyConfigured("PASSKEY_ORIGIN contains an invalid port.") from exc
    if origin_port == 0:
        raise ImproperlyConfigured("PASSKEY_ORIGIN contains an invalid port.")
    if origin_parts.hostname != rp_id and not origin_parts.hostname.endswith(f".{rp_id}"):
        raise ImproperlyConfigured("PASSKEY_ORIGIN must use PASSKEY_RP_ID or one of its subdomains.")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if origin_parts.scheme != "https" and not (origin_parts.scheme == "http" and origin_parts.hostname in local_hosts):
        raise ImproperlyConfigured("PASSKEY_ORIGIN must use HTTPS except on localhost.")
    return rp_id, settings.PASSKEY_RP_NAME, origin


def _consume_challenge(
    session: MutableMapping[str, Any],
    session_key: str,
    *,
    expected_user_id: int | None = None,
) -> bytes:
    state = session.pop(session_key, None)
    if not isinstance(state, dict):
        raise PasskeyCeremonyError("Challenge is missing.")
    if expected_user_id is not None and state.get("user_id") != expected_user_id:
        raise PasskeyCeremonyError("Challenge belongs to another user.")
    created_at = state.get("created_at")
    if not isinstance(created_at, int):
        raise PasskeyCeremonyError("Challenge timestamp is invalid.")
    age = int(time.time()) - created_at
    if age < 0 or age > settings.PASSKEY_CHALLENGE_TTL_SECONDS:
        raise PasskeyCeremonyError("Challenge has expired.")
    challenge = state.get("challenge")
    if not isinstance(challenge, str):
        raise PasskeyCeremonyError("Challenge is invalid.")
    try:
        return base64url_to_bytes(challenge)
    except ValueError as exc:
        raise PasskeyCeremonyError("Challenge is invalid.") from exc


def begin_passkey_registration(user: User, session: MutableMapping[str, Any]) -> str:
    """Generate registration options and bind the challenge to the current user session."""
    rp_id, rp_name, _origin = _require_passkey_settings()
    user_name = getattr(user, "email", "") or user.get_username()
    excluded_credentials = [
        PublicKeyCredentialDescriptor(id=bytes(credential_id))
        for credential_id in PasskeyCredential.objects.filter(user=user).values_list("credential_id", flat=True)
    ]
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=user.pk.to_bytes(8, byteorder="big", signed=False),
        user_name=user_name,
        user_display_name=user.get_full_name() or user_name,
        exclude_credentials=excluded_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    session[REGISTRATION_CHALLENGE_SESSION_KEY] = {
        "challenge": bytes_to_base64url(options.challenge),
        "user_id": user.pk,
        "created_at": int(time.time()),
    }
    return options_to_json(options)


def finish_passkey_registration(
    user: User,
    session: MutableMapping[str, Any],
    credential_data: dict[str, Any],
    *,
    name: str,
) -> PasskeyCredential:
    """Verify a registration response and persist the resulting public credential."""
    challenge = _consume_challenge(
        session,
        REGISTRATION_CHALLENGE_SESSION_KEY,
        expected_user_id=user.pk,
    )
    rp_id, _rp_name, origin = _require_passkey_settings()
    verified = verify_registration_response(
        credential=credential_data,
        expected_challenge=challenge,
        expected_rp_id=rp_id,
        expected_origin=origin,
        require_user_verification=True,
    )
    response = credential_data.get("response")
    raw_transports = response.get("transports", []) if isinstance(response, dict) else []
    transports = [item for item in raw_transports if isinstance(item, str) and item in ALLOWED_TRANSPORTS]
    return PasskeyCredential.objects.create(
        user=user,
        name=name,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=transports,
        device_type=verified.credential_device_type.value,
        backed_up=verified.credential_backed_up,
    )


def begin_passkey_authentication(session: MutableMapping[str, Any]) -> str:
    """Generate discoverable-credential authentication options for the current session."""
    rp_id, _rp_name, _origin = _require_passkey_settings()
    options = generate_authentication_options(
        rp_id=rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    session[AUTHENTICATION_CHALLENGE_SESSION_KEY] = {
        "challenge": bytes_to_base64url(options.challenge),
        "created_at": int(time.time()),
    }
    return options_to_json(options)


@transaction.atomic
def finish_passkey_authentication(
    session: MutableMapping[str, Any],
    credential_data: dict[str, Any],
) -> User:
    """Verify a passkey assertion and atomically update the credential state."""
    challenge = _consume_challenge(session, AUTHENTICATION_CHALLENGE_SESSION_KEY)
    credential_id = credential_data.get("id")
    if not isinstance(credential_id, str):
        raise PasskeyCeremonyError("Authentication response is invalid.")

    try:
        credential_id_bytes = base64url_to_bytes(credential_id)
        credential = (
            PasskeyCredential.objects.select_for_update().select_related("user").get(credential_id=credential_id_bytes)
        )
    except (PasskeyCredential.DoesNotExist, ValueError) as exc:
        raise PasskeyCeremonyError("Authentication response is invalid.") from exc
    if not credential.user.is_active:
        raise PasskeyCeremonyError("Authentication response is invalid.")

    rp_id, _rp_name, origin = _require_passkey_settings()
    verified = verify_authentication_response(
        credential=credential_data,
        expected_challenge=challenge,
        expected_rp_id=rp_id,
        expected_origin=origin,
        credential_public_key=bytes(credential.public_key),
        credential_current_sign_count=credential.sign_count,
        require_user_verification=True,
    )
    if verified.credential_id != bytes(credential.credential_id):
        raise PasskeyCeremonyError("Authentication response is invalid.")

    credential.sign_count = verified.new_sign_count
    credential.device_type = verified.credential_device_type.value
    credential.backed_up = verified.credential_backed_up
    credential.last_used_at = timezone.now()
    credential.save(update_fields=["sign_count", "device_type", "backed_up", "last_used_at", "updated_at"])
    return credential.user
