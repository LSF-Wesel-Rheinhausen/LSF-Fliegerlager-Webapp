"""Lifecycle helpers for delivery-activated account-recovery capabilities."""

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import AccountRecoveryToken, Participant, ParticipantFamilyMember

User = get_user_model()
RECOVERY_TOKEN_PLACEHOLDER = "ACCOUNT_RECOVERY_TOKEN"


def recovery_token_digest(raw_token: str) -> str:
    """Return the irreversible lookup value persisted for one bearer token."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _token_timeout() -> timedelta:
    timeout_seconds = max(1, int(getattr(settings, "ACCOUNT_RECOVERY_TIMEOUT_SECONDS", 3600)))
    return timedelta(seconds=timeout_seconds)


def _owner_filter(kind: str, owner: Any) -> dict[str, Any]:
    if kind == AccountRecoveryToken.Kind.USER_PASSWORD:
        return {"user": owner}
    if kind == AccountRecoveryToken.Kind.PARTICIPANT_PIN:
        return {"participant": owner}
    if kind == AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN:
        return {"family_member": owner}
    raise ValueError("Unsupported account-recovery kind")


def _pin_hash(owner: Any) -> str:
    try:
        return str(owner.pin.pin_hash)
    except ObjectDoesNotExist:
        return ""


def credential_fingerprint(kind: str, owner: Any) -> str:
    """Snapshot the current credential without duplicating its reusable hash."""
    credential_hash = str(owner.password) if kind == AccountRecoveryToken.Kind.USER_PASSWORD else _pin_hash(owner)
    return salted_hmac(
        "billing.account-recovery-credential",
        credential_hash,
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


def recovery_owner_is_active(kind: str, owner: Any) -> bool:
    """Return whether an owner is still eligible to use the requested login surface."""
    if kind == AccountRecoveryToken.Kind.USER_PASSWORD:
        return bool(owner.is_active)
    if kind == AccountRecoveryToken.Kind.PARTICIPANT_PIN:
        return bool(
            owner.archived_at is None and owner.camp.is_active and owner.status != Participant.Status.PENDING_APPROVAL
        )
    if kind == AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN:
        guardian = owner.guardian
        return bool(
            owner.is_active
            and owner.role == ParticipantFamilyMember.Role.COMPANION
            and guardian.archived_at is None
            and guardian.camp.is_active
            and guardian.status != Participant.Status.PENDING_APPROVAL
        )
    return False


def invalidate_account_recovery_tokens(*, kind: str, owner: Any) -> None:
    """Invalidate every outstanding token for one credential owner."""
    AccountRecoveryToken.objects.filter(kind=kind, used_at__isnull=True, **_owner_filter(kind, owner)).update(
        used_at=timezone.now()
    )


def create_account_recovery_token(*, kind: str, owner: Any) -> AccountRecoveryToken:
    """Create an inactive token record that contains no bearer secret."""
    return AccountRecoveryToken.objects.create(
        kind=kind,
        credential_fingerprint=credential_fingerprint(kind, owner),
        **_owner_filter(kind, owner),
    )


def _initial_recovery(recovery_id: int) -> AccountRecoveryToken | None:
    return (
        AccountRecoveryToken.objects.select_related(
            "user",
            "participant",
            "participant__camp",
            "family_member",
            "family_member__guardian",
            "family_member__guardian__camp",
        )
        .filter(pk=recovery_id)
        .first()
    )


def _lock_owner(recovery: AccountRecoveryToken) -> Any | None:
    if recovery.user_id is not None:
        return User.objects.select_for_update().filter(pk=recovery.user_id).first()
    if recovery.participant_id is not None:
        return Participant.objects.select_related("camp").select_for_update().filter(pk=recovery.participant_id).first()
    if recovery.family_member_id is not None:
        return (
            ParticipantFamilyMember.objects.select_related("guardian", "guardian__camp")
            .select_for_update()
            .filter(pk=recovery.family_member_id)
            .first()
        )
    return None


def _matches_owner(recovery: AccountRecoveryToken, owner: Any) -> bool:
    owner_id = getattr(owner, "pk", None)
    if recovery.kind == AccountRecoveryToken.Kind.USER_PASSWORD:
        return owner_id is not None and owner_id == recovery.user_id
    if recovery.kind == AccountRecoveryToken.Kind.PARTICIPANT_PIN:
        return owner_id is not None and owner_id == recovery.participant_id
    if recovery.kind == AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN:
        return owner_id is not None and owner_id == recovery.family_member_id
    return False


def recovery_matches_current_credential(recovery: AccountRecoveryToken, owner: Any) -> bool:
    """Return whether account state still matches the token's issuance snapshot."""
    return bool(
        _matches_owner(recovery, owner)
        and recovery_owner_is_active(recovery.kind, owner)
        and recovery.credential_fingerprint == credential_fingerprint(recovery.kind, owner)
    )


@transaction.atomic
def activate_account_recovery_token(recovery_id: int) -> str | None:
    """Create a fresh in-memory bearer secret immediately before one delivery attempt."""
    initial = _initial_recovery(recovery_id)
    if initial is None:
        return None
    owner = _lock_owner(initial)
    if owner is None:
        return None
    recovery = AccountRecoveryToken.objects.select_for_update().filter(pk=recovery_id).first()
    if recovery is None or recovery.used_at is not None or not recovery_matches_current_credential(recovery, owner):
        return None
    raw_token = secrets.token_urlsafe(32)
    now = timezone.now()
    recovery.token_digest = recovery_token_digest(raw_token)
    recovery.expires_at = now + _token_timeout()
    recovery.save(update_fields=["token_digest", "expires_at", "updated_at"])
    return raw_token


def find_valid_account_recovery(raw_token: str) -> AccountRecoveryToken | None:
    """Find an active token whose owner credential has not changed."""
    recovery = (
        AccountRecoveryToken.objects.select_related(
            "user",
            "participant",
            "participant__camp",
            "family_member",
            "family_member__guardian",
            "family_member__guardian__camp",
        )
        .filter(
            token_digest=recovery_token_digest(raw_token),
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if recovery is None:
        return None
    owner = recovery.user or recovery.participant or recovery.family_member
    return recovery if owner is not None and recovery_matches_current_credential(recovery, owner) else None


def lock_valid_account_recovery(recovery_id: int, raw_token: str) -> tuple[AccountRecoveryToken, Any] | None:
    """Lock the owner before its token and revalidate both inside the caller's transaction."""
    initial = _initial_recovery(recovery_id)
    if initial is None:
        return None
    owner = _lock_owner(initial)
    if owner is None:
        return None
    recovery = (
        AccountRecoveryToken.objects.select_for_update()
        .filter(
            pk=recovery_id,
            token_digest=recovery_token_digest(raw_token),
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if recovery is None or not recovery_matches_current_credential(recovery, owner):
        return None
    return recovery, owner
