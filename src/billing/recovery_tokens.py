"""Lifecycle helpers for delivery-activated account-recovery capabilities."""

import hashlib
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import is_password_usable
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import (
    AccountRecoveryToken,
    EmailBatch,
    EmailDelivery,
    Participant,
    ParticipantFamilyMember,
    ParticipantFamilyMemberPin,
    ParticipantPin,
    PushMessage,
    PushSubscription,
)
from .push_endpoints import is_allowed_push_endpoint

User = get_user_model()
RECOVERY_TOKEN_PLACEHOLDER = "ACCOUNT_RECOVERY_TOKEN"
RECOVERY_ARTIFACT_RETENTION = timedelta(days=30)


@transaction.atomic
def cleanup_account_recovery_artifacts(*, now: Any | None = None, batch_size: int = 100) -> int:
    """Delete terminal recovery capabilities and their private delivery metadata."""
    cleanup_time = now or timezone.now()
    active_statuses = [EmailDelivery.Status.PENDING, EmailDelivery.Status.PROCESSING]
    candidates = (
        AccountRecoveryToken.objects.annotate(
            has_active_email=Exists(
                EmailDelivery.objects.filter(
                    account_recovery_id=OuterRef("pk"),
                    status__in=active_statuses,
                )
            ),
            has_active_push=Exists(
                PushMessage.objects.filter(
                    account_recovery_id=OuterRef("pk"),
                    status__in=[PushMessage.Status.PENDING, PushMessage.Status.PROCESSING],
                )
            ),
        )
        .filter(has_active_email=False, has_active_push=False)
        .filter(
            Q(used_at__isnull=False)
            | Q(expires_at__lte=cleanup_time)
            | Q(
                token_digest__isnull=True,
                expires_at__isnull=True,
                updated_at__lt=cleanup_time - RECOVERY_ARTIFACT_RETENTION,
            )
        )
        .order_by("updated_at", "pk")
    )
    recovery_ids = list(candidates.select_for_update().values_list("pk", flat=True)[: max(1, batch_size)])
    if recovery_ids:
        AccountRecoveryToken.objects.filter(pk__in=recovery_ids).delete()
        EmailBatch.objects.filter(kind=EmailBatch.Kind.ACCOUNT_RECOVERY, deliveries__isnull=True).delete()
    return len(recovery_ids)


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


def has_usable_recovery_credential(kind: str, owner: Any) -> bool:
    """Return whether recovery replaces an established, usable login credential."""
    if kind == AccountRecoveryToken.Kind.USER_PASSWORD:
        return bool(getattr(owner, "has_usable_password", lambda: False)())
    try:
        pin = owner.pin
    except ObjectDoesNotExist:
        return False
    return bool(pin.pin_hash and is_password_usable(pin.pin_hash) and not pin.must_set_pin)


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


def revoke_owner_recovery_push_subscriptions(*, kind: str, owner: Any) -> None:
    """Revoke exactly one credential owner's devices after an established rotation.

    Callers hold the owner (and, for PIN credentials, PIN) row first.  This
    helper then locks recovery capabilities before subscriptions, establishing
    the shared ``owner -> PIN -> recovery token -> subscription`` order.
    """
    owner_filter = _owner_filter(kind, owner)
    list(
        AccountRecoveryToken.objects.select_for_update()
        .filter(kind=kind, used_at__isnull=True, **owner_filter)
        .order_by("pk")
    )
    updates = {"is_active": False}
    if kind != AccountRecoveryToken.Kind.USER_PASSWORD:
        updates["identity_verified"] = False
    subscription_ids = list(
        PushSubscription.objects.select_for_update().filter(**owner_filter).order_by("pk").values_list("pk", flat=True)
    )
    if subscription_ids:
        PushSubscription.objects.filter(pk__in=subscription_ids).update(updated_at=timezone.now(), **updates)


def lock_push_subscription_registration(
    *, kind: str, owner: Any, endpoint: str, expected_credential_fingerprint: str
) -> tuple[bool, PushSubscription | None]:
    """Lock registration state in the shared owner/PIN/token/subscription order.

    The caller must hold the surrounding transaction until the subscription
    update commits.  This serializes reactivation with credential rotation.
    """
    locked_owner: Any | None
    if kind == AccountRecoveryToken.Kind.USER_PASSWORD:
        locked_owner = User.objects.select_for_update().filter(pk=owner.pk).first()
        owner_filter = {"user": owner}
    elif kind == AccountRecoveryToken.Kind.PARTICIPANT_PIN:
        locked_owner = Participant.objects.select_for_update().filter(pk=owner.pk).first()
        ParticipantPin.objects.select_for_update().filter(participant_id=owner.pk).first()
        owner_filter = {"participant": owner}
    elif kind == AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN:
        locked_owner = ParticipantFamilyMember.objects.select_for_update().filter(pk=owner.pk).first()
        ParticipantFamilyMemberPin.objects.select_for_update().filter(family_member_id=owner.pk).first()
        owner_filter = {"family_member": owner}
    else:
        raise ValueError("Unsupported recovery kind")
    if (
        locked_owner is None
        or not recovery_owner_is_active(kind, locked_owner)
        or not constant_time_compare(
            credential_fingerprint(kind, locked_owner),
            expected_credential_fingerprint,
        )
    ):
        return False, None
    list(
        AccountRecoveryToken.objects.select_for_update()
        .filter(kind=kind, used_at__isnull=True, **owner_filter)
        .order_by("pk")
    )
    subscription = PushSubscription.objects.select_for_update().filter(endpoint=endpoint).first()
    return True, subscription


@transaction.atomic
def revoke_owned_push_subscription(*, subscription_id: int, owner: Any) -> bool:
    """Delete one authorized device after acquiring the shared recovery lock order.

    The subscription may be referenced by recovery tokens through ``SET_NULL``.
    Locking the owner, its PIN where applicable, all outstanding tokens, and
    finally the subscription prevents that collector update from deadlocking
    with credential rotation and recovery delivery transactions.
    """
    owner_filter: dict[str, Any]
    if isinstance(owner, User):
        owner_filter = {"user": owner}
        User.objects.select_for_update().filter(pk=owner.pk).first()
    elif isinstance(owner, ParticipantFamilyMember):
        owner_filter = {"family_member": owner}
        ParticipantFamilyMember.objects.select_related("guardian", "guardian__camp").select_for_update().filter(
            pk=owner.pk
        ).first()
        ParticipantFamilyMemberPin.objects.select_for_update().filter(family_member_id=owner.pk).first()
    elif isinstance(owner, Participant):
        owner_filter = {"participant": owner}
        Participant.objects.select_related("camp").select_for_update().filter(pk=owner.pk).first()
        ParticipantPin.objects.select_for_update().filter(participant_id=owner.pk).first()
    else:
        raise TypeError("Unsupported push-subscription owner")

    kind = (
        AccountRecoveryToken.Kind.USER_PASSWORD
        if isinstance(owner, User)
        else (
            AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN
            if isinstance(owner, ParticipantFamilyMember)
            else AccountRecoveryToken.Kind.PARTICIPANT_PIN
        )
    )
    list(AccountRecoveryToken.objects.select_for_update().filter(kind=kind, **owner_filter).order_by("pk"))
    subscription = PushSubscription.objects.select_for_update().filter(pk=subscription_id, **owner_filter).first()
    if subscription is None:
        return False
    subscription.delete()
    return True


@transaction.atomic
def consume_account_recovery_token(recovery_id: int) -> None:
    """Terminally invalidate one capability while preserving the owner/token lock order."""
    initial = _initial_recovery(recovery_id)
    if initial is None:
        return
    _lock_owner(initial)
    recovery = AccountRecoveryToken.objects.select_for_update().filter(pk=recovery_id).first()
    if recovery is None:
        return
    recovery.used_at = recovery.used_at or timezone.now()
    recovery.token_digest = None
    recovery.expires_at = None
    recovery.save(update_fields=["used_at", "token_digest", "expires_at", "updated_at"])


@transaction.atomic
def terminally_fail_account_recovery_push_delivery(
    *,
    recovery_id: int,
    subscription_id: int,
    message_id: int,
    error_code: str,
    remove_subscription: bool,
    preserve_capability: bool = False,
) -> tuple[bool, int | None]:
    """Terminalize a recovery push delivery in a consistent lock order.

    The capability may be preserved when the transport outcome is ambiguous.
    Returns whether the subscription was removed and the final message attempt
    count. No bearer secret is read or persisted while handling a failure.
    """
    initial = _initial_recovery(recovery_id)
    if initial is None:
        return False, None
    _lock_owner(initial)
    recovery = AccountRecoveryToken.objects.select_for_update().filter(pk=recovery_id).first()
    subscription = PushSubscription.objects.select_for_update().filter(pk=subscription_id).first()
    message = PushMessage.objects.select_for_update().filter(pk=message_id).first()
    if recovery is not None and not preserve_capability:
        recovery.used_at = recovery.used_at or timezone.now()
        recovery.token_digest = None
        recovery.expires_at = None
        recovery.save(update_fields=["used_at", "token_digest", "expires_at", "updated_at"])
    if message is None:
        return False, None
    if remove_subscription and subscription is not None:
        subscription.delete()
        return True, message.attempts
    message.status = PushMessage.Status.FAILED
    message.last_error_code = error_code
    message.processing_started_at = None
    message.attempts += 1
    message.save(update_fields=["status", "last_error_code", "processing_started_at", "attempts", "updated_at"])
    return False, message.attempts


@transaction.atomic
def retry_account_recovery_push_delivery(
    *, recovery_id: int, subscription_id: int, message_id: int, error_code: str, next_attempt_at: Any
) -> int | None:
    """Retry a recovery push while acquiring owner/token/subscription/message locks in order."""
    initial = _initial_recovery(recovery_id)
    if initial is None:
        return None
    _lock_owner(initial)
    recovery = AccountRecoveryToken.objects.select_for_update().filter(pk=recovery_id).first()
    subscription = PushSubscription.objects.select_for_update().filter(pk=subscription_id).first()
    message = PushMessage.objects.select_for_update().filter(pk=message_id).first()
    if recovery is None:
        return None
    if subscription is None or message is None:
        recovery.used_at = recovery.used_at or timezone.now()
        recovery.token_digest = None
        recovery.expires_at = None
        recovery.save(update_fields=["used_at", "token_digest", "expires_at", "updated_at"])
        return None
    message.attempts += 1
    message.processing_started_at = None
    message.last_error_code = error_code
    message.status = PushMessage.Status.PENDING
    message.next_attempt_at = next_attempt_at
    message.save(
        update_fields=[
            "attempts",
            "last_error_code",
            "status",
            "processing_started_at",
            "next_attempt_at",
            "updated_at",
        ]
    )
    return message.attempts


@transaction.atomic
def complete_account_recovery_push_delivery(
    *, recovery_id: int, subscription_id: int, message_id: int, sent_at: Any
) -> bool:
    """Mark a recovery push sent while acquiring owner/token/subscription/message locks in order."""
    initial = _initial_recovery(recovery_id)
    if initial is None:
        return False
    _lock_owner(initial)
    recovery = AccountRecoveryToken.objects.select_for_update().filter(pk=recovery_id).first()
    subscription = PushSubscription.objects.select_for_update().filter(pk=subscription_id).first()
    message = PushMessage.objects.select_for_update().filter(pk=message_id).first()
    if recovery is None:
        return False
    if subscription is None or message is None:
        recovery.used_at = recovery.used_at or timezone.now()
        recovery.token_digest = None
        recovery.expires_at = None
        recovery.save(update_fields=["used_at", "token_digest", "expires_at", "updated_at"])
        return False
    message.status = PushMessage.Status.SENT
    message.processing_started_at = None
    message.sent_at = sent_at
    message.attempts += 1
    message.last_error_code = ""
    message.save(
        update_fields=["status", "processing_started_at", "sent_at", "attempts", "last_error_code", "updated_at"]
    )
    subscription.last_success_at = sent_at
    subscription.failure_count = 0
    subscription.save(update_fields=["last_success_at", "failure_count", "updated_at"])
    return True


def create_account_recovery_token(*, kind: str, owner: Any, kiosk_mode: str | None = None) -> AccountRecoveryToken:
    """Create an inactive token record that contains no bearer secret."""
    if kind != AccountRecoveryToken.Kind.USER_PASSWORD and kiosk_mode is None:
        kiosk_mode = AccountRecoveryToken.KioskMode.PRIVATE
    return AccountRecoveryToken.objects.create(
        kind=kind,
        delivery_channel=AccountRecoveryToken.DeliveryChannel.PUSH,
        kiosk_mode=kiosk_mode,
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
    owner: Any | None = None
    if recovery.user_id is not None:
        owner = User.objects.select_for_update().filter(pk=recovery.user_id).first()
    elif recovery.participant_id is not None:
        participants = Participant.objects.select_related("camp").select_for_update()
        owner = participants.filter(pk=recovery.participant_id).first()
    elif recovery.family_member_id is not None:
        owner = (
            ParticipantFamilyMember.objects.select_related("guardian", "guardian__camp")
            .select_for_update()
            .filter(pk=recovery.family_member_id)
            .first()
        )
    if owner is not None:
        if recovery.kind == AccountRecoveryToken.Kind.PARTICIPANT_PIN:
            ParticipantPin.objects.select_for_update().filter(participant_id=owner.pk).first()
        elif recovery.kind == AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN:
            ParticipantFamilyMemberPin.objects.select_for_update().filter(family_member_id=owner.pk).first()
    return owner


def _matches_owner(recovery: AccountRecoveryToken, owner: Any) -> bool:
    owner_id = getattr(owner, "pk", None)
    if recovery.kind == AccountRecoveryToken.Kind.USER_PASSWORD:
        return owner_id is not None and owner_id == recovery.user_id
    if recovery.kind == AccountRecoveryToken.Kind.PARTICIPANT_PIN:
        return owner_id is not None and owner_id == recovery.participant_id
    if recovery.kind == AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN:
        return owner_id is not None and owner_id == recovery.family_member_id
    return False


def _normalized_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    try:
        validate_email(normalized)
    except ValidationError:
        return None
    return normalized


def _matches_delivery_address(owner: Any, recipient_email: str | None) -> bool:
    """Return whether a queued email still targets the owner's current address."""
    if recipient_email is None:
        return True
    queued_email = _normalized_email(recipient_email)
    owner_email = _normalized_email(getattr(owner, "email", None))
    return queued_email is not None and queued_email == owner_email


def _recipient_email_digest(email: str) -> str:
    return salted_hmac(
        "billing.account-recovery-recipient", email, secret=settings.SECRET_KEY, algorithm="sha256"
    ).hexdigest()


@transaction.atomic
def bind_account_recovery_email_recipient(recovery: AccountRecoveryToken, recipient_email: str) -> None:
    """Bind one unused capability to its current owner's normalized email address."""
    normalized_email = _normalized_email(recipient_email)
    if normalized_email is None:
        raise ValueError("Recovery recipient address is invalid")
    initial = _initial_recovery(recovery.pk)
    if initial is None:
        raise ValueError("Recovery capability does not exist")
    owner = _lock_owner(initial)
    locked = AccountRecoveryToken.objects.select_for_update().filter(pk=recovery.pk).first()
    if (
        owner is None
        or locked is None
        or locked.used_at is not None
        or locked.token_digest is not None
        or locked.expires_at is not None
        or locked.delivery_channel != AccountRecoveryToken.DeliveryChannel.PUSH
        or locked.recipient_email_digest is not None
        or not _matches_delivery_address(owner, normalized_email)
        or not has_usable_recovery_credential(locked.kind, owner)
        or not recovery_owner_is_active(locked.kind, owner)
        or locked.credential_fingerprint != credential_fingerprint(locked.kind, owner)
    ):
        raise ValueError("Recovery capability cannot be bound to this recipient")
    digest = _recipient_email_digest(normalized_email)
    locked.delivery_channel = AccountRecoveryToken.DeliveryChannel.EMAIL
    locked.recipient_email_digest = digest
    locked.save(update_fields=["delivery_channel", "recipient_email_digest", "updated_at"])
    recovery.delivery_channel = locked.delivery_channel
    recovery.recipient_email_digest = digest


def _matches_bound_recipient(recovery: AccountRecoveryToken, owner: Any) -> bool:
    if recovery.delivery_channel == AccountRecoveryToken.DeliveryChannel.PUSH:
        return recovery.recipient_email_digest is None
    owner_email = _normalized_email(getattr(owner, "email", None))
    return bool(
        owner_email
        and recovery.recipient_email_digest
        and constant_time_compare(recovery.recipient_email_digest, _recipient_email_digest(owner_email))
    )


def _matches_bound_push_subscription(recovery: AccountRecoveryToken, owner: Any) -> bool:
    """Return whether the exact device that received a push link remains valid."""
    if recovery.delivery_channel != AccountRecoveryToken.DeliveryChannel.PUSH:
        return recovery.delivery_subscription_id is None
    if recovery.delivery_subscription_id is None:
        return not recovery.push_delivery_bound
    subscription = PushSubscription.objects.filter(
        pk=recovery.delivery_subscription_id,
        is_active=True,
        identity_verified=True,
    ).first()
    if subscription is None:
        return False
    if recovery.kind == AccountRecoveryToken.Kind.USER_PASSWORD:
        return subscription.user_id == owner.pk
    if recovery.kind == AccountRecoveryToken.Kind.PARTICIPANT_PIN:
        return subscription.participant_id == owner.pk
    return subscription.family_member_id == owner.pk


def recovery_matches_current_credential(recovery: AccountRecoveryToken, owner: Any) -> bool:
    """Return whether account state still matches the token's issuance snapshot."""
    return bool(
        _matches_owner(recovery, owner)
        and _matches_bound_recipient(recovery, owner)
        and _matches_bound_push_subscription(recovery, owner)
        and has_usable_recovery_credential(recovery.kind, owner)
        and recovery_owner_is_active(recovery.kind, owner)
        and recovery.credential_fingerprint == credential_fingerprint(recovery.kind, owner)
    )


def _activate_locked_recovery(recovery: AccountRecoveryToken, owner: Any) -> str | None:
    if (
        recovery.used_at is not None
        or (recovery.expires_at is not None and recovery.expires_at <= timezone.now())
        or not recovery_matches_current_credential(recovery, owner)
    ):
        return None
    if recovery.expires_at is None:
        recovery.expires_at = timezone.now() + _token_timeout()
    # Derive the bearer from immutable, capability-bound state.  This lets a
    # worker retry after provider acceptance without storing the bearer itself.
    binding = recovery.recipient_email_digest or str(recovery.delivery_subscription_id or "")
    raw_token = salted_hmac(
        "billing.account-recovery-token",
        f"{recovery.pk}:{recovery.credential_fingerprint}:{binding}:{recovery.expires_at.isoformat()}",
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()
    recovery.token_digest = recovery_token_digest(raw_token)
    recovery.save(update_fields=["token_digest", "expires_at", "updated_at"])
    return raw_token


@transaction.atomic
def activate_account_recovery_token(recovery_id: int, *, recipient_email: str | None = None) -> str | None:
    """Derive the delivery-bound bearer without persisting the raw secret."""
    initial = _initial_recovery(recovery_id)
    if initial is None:
        return None
    owner = _lock_owner(initial)
    if owner is None:
        return None
    recovery = AccountRecoveryToken.objects.select_for_update().filter(pk=recovery_id).first()
    if recovery is None or not _matches_delivery_address(owner, recipient_email):
        return None
    return _activate_locked_recovery(recovery, owner)


@transaction.atomic
def activate_account_recovery_push_token(
    recovery_id: int,
    *,
    subscription_id: int,
) -> str | None:
    """Lock and activate a push capability only for the exact current subscription owner."""
    initial = _initial_recovery(recovery_id)
    if initial is None:
        return None
    owner = _lock_owner(initial)
    if owner is None:
        return None
    recovery = AccountRecoveryToken.objects.select_for_update().filter(pk=recovery_id).first()
    if recovery is None or recovery.delivery_channel != AccountRecoveryToken.DeliveryChannel.PUSH:
        return None
    subscription = PushSubscription.objects.select_for_update().filter(pk=subscription_id, is_active=True).first()
    if subscription is None:
        return None
    if not is_allowed_push_endpoint(subscription.endpoint):
        PushSubscription.objects.filter(pk=subscription.pk).update(is_active=False, updated_at=timezone.now())
        return None
    subscription_matches = bool(
        (recovery.kind == AccountRecoveryToken.Kind.USER_PASSWORD and subscription.user_id == owner.pk)
        or (recovery.kind == AccountRecoveryToken.Kind.PARTICIPANT_PIN and subscription.participant_id == owner.pk)
        or (recovery.kind == AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN and subscription.family_member_id == owner.pk)
    )
    requires_verified_identity = recovery.kind != AccountRecoveryToken.Kind.USER_PASSWORD
    if not subscription_matches or (requires_verified_identity and not subscription.identity_verified):
        return None
    recovery.delivery_subscription = subscription
    recovery.push_delivery_bound = True
    recovery.save(update_fields=["delivery_subscription", "push_delivery_bound", "updated_at"])
    return _activate_locked_recovery(recovery, owner)


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
