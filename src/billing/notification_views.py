import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .models import Participant, PushSubscription
from .notifications import allowed_categories, queue_participant_notification, queue_user_notification
from .pwa_views import pwa_template_context
from .views import KIOSK_MODE_SESSION_KEY, KIOSK_PARTICIPANT_SESSION_KEY, _kiosk_context


def _json_payload(request: HttpRequest) -> dict[str, Any] | None:
    try:
        value = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _private_participant(request: HttpRequest) -> Participant | None:
    if request.session.get(KIOSK_MODE_SESSION_KEY) != "private":
        return None
    participant_id = request.session.get(KIOSK_PARTICIPANT_SESSION_KEY)
    if not isinstance(participant_id, int):
        return None
    return Participant.objects.filter(
        pk=participant_id,
        archived_at__isnull=True,
        camp__is_active=True,
    ).first()


def _owner_filter(owner: Any, participant_owner: bool) -> dict[str, Any]:
    return (
        {"participant": owner, "user__isnull": True}
        if participant_owner
        else {"user": owner, "participant__isnull": True}
    )


def _endpoint_fingerprint(endpoint: str) -> str:
    """Return a stable, non-sensitive identifier for a push endpoint."""
    return hashlib.sha256(endpoint.encode()).hexdigest()


def _device_payload(subscription: PushSubscription) -> dict[str, Any]:
    """Serialize device state without exposing its private push endpoint."""
    return {
        "id": subscription.pk,
        "device_name": subscription.device_name,
        "categories": list(subscription.categories),
        "last_success_at": subscription.last_success_at,
        "endpoint_fingerprint": _endpoint_fingerprint(subscription.endpoint),
    }


def _device_name(payload: dict[str, Any] | None) -> str | None:
    """Return a normalized valid device name from a JSON payload."""
    if payload is None:
        return None
    value = payload.get("device_name")
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if 1 <= len(normalized) <= 80 else None


def _category_selection(payload: dict[str, Any] | None, allowed: dict[str, str]) -> list[str] | None:
    """Return a non-empty, deduplicated selection restricted to allowed categories."""
    if payload is None:
        return None
    categories = payload.get("categories")
    if (
        not isinstance(categories, list)
        or not categories
        or any(not isinstance(category, str) or category not in allowed for category in categories)
    ):
        return None
    return list(dict.fromkeys(categories))


def _settings_response(request: HttpRequest, owner: Any, *, participant_owner: bool) -> HttpResponse:
    subscriptions = [
        _device_payload(subscription)
        for subscription in PushSubscription.objects.filter(**_owner_filter(owner, participant_owner))
    ]
    context = {
        "subscriptions": subscriptions,
        "notification_categories": allowed_categories(participant_owner=participant_owner),
        "web_push_public_key": settings.WEB_PUSH_VAPID_PUBLIC_KEY,
        "notification_subscribe_url": (
            "/kiosk/notifications/subscriptions/" if participant_owner else "/notifications/subscriptions/"
        ),
        "notification_subscription_base_url": (
            "/kiosk/notifications/subscriptions/" if participant_owner else "/notifications/subscriptions/"
        ),
    }
    if participant_owner:
        return render(
            request,
            "billing/kiosk_notification_settings.html",
            {**context, **_kiosk_context("private"), "participant": owner},
        )
    return render(request, "billing/notification_settings.html", {**context, **pwa_template_context("admin")})


@login_required
def notification_settings(request: HttpRequest) -> HttpResponse:
    """Render push-device settings for the current administrative user."""
    return _settings_response(request, request.user, participant_owner=False)


def kiosk_notification_settings(request: HttpRequest) -> HttpResponse:
    """Render push-device settings for a private kiosk participant."""
    participant = _private_participant(request)
    if participant is None:
        return JsonResponse({"error": "Private Kiosk-Anmeldung erforderlich."}, status=403)
    return _settings_response(request, participant, participant_owner=True)


def _subscribe(request: HttpRequest, owner: Any, *, participant_owner: bool) -> JsonResponse:
    if not settings.WEB_PUSH_ENABLED:
        return JsonResponse({"error": "Push-Benachrichtigungen sind deaktiviert."}, status=503)
    payload = _json_payload(request)
    if payload is None:
        return JsonResponse({"error": "Ungültiges JSON."}, status=400)
    endpoint = payload.get("endpoint")
    keys = payload.get("keys")
    device_name = payload.get("device_name", "Dieses Gerät")
    allowed = allowed_categories(participant_owner=participant_owner)
    if not isinstance(endpoint, str) or len(endpoint) > 2048 or urlsplit(endpoint).scheme != "https":
        return JsonResponse({"error": "Ungültiger Push-Endpoint."}, status=400)
    if not isinstance(keys, dict) or not all(isinstance(keys.get(key), str) for key in ("p256dh", "auth")):
        return JsonResponse({"error": "Ungültige Browser-Schlüssel."}, status=400)
    if any(len(keys[key]) > 512 or not keys[key] for key in ("p256dh", "auth")):
        return JsonResponse({"error": "Ungültige Browser-Schlüssel."}, status=400)
    normalized_device_name = _device_name({"device_name": device_name})
    if normalized_device_name is None:
        return JsonResponse({"error": "Ungültiger Gerätename."}, status=400)
    categories = _category_selection(payload, allowed)
    if categories is None:
        return JsonResponse({"error": "Ungültige Benachrichtigungskategorie."}, status=400)

    existing = PushSubscription.objects.filter(endpoint=endpoint).first()
    owner_matches = existing is not None and (
        (participant_owner and existing.participant_id == owner.pk and existing.user_id is None)
        or (not participant_owner and existing.user_id == owner.pk and existing.participant_id is None)
    )
    if existing is not None and not owner_matches:
        return JsonResponse({"error": "Dieses Gerät ist bereits einem anderen Konto zugeordnet."}, status=409)
    owner_values = {"participant": owner, "user": None} if participant_owner else {"user": owner, "participant": None}
    subscription, created = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            **owner_values,
            "p256dh": keys["p256dh"],
            "auth": keys["auth"],
            "device_name": normalized_device_name,
            "categories": categories,
            "is_active": True,
            "failure_count": 0,
        },
    )
    return JsonResponse({"device": _device_payload(subscription)}, status=201 if created else 200)


@login_required
@require_POST
def notification_subscribe(request: HttpRequest) -> JsonResponse:
    """Create or update the current user's browser subscription."""
    return _subscribe(request, request.user, participant_owner=False)


@require_POST
def kiosk_notification_subscribe(request: HttpRequest) -> JsonResponse:
    """Create or update a private participant browser subscription."""
    participant = _private_participant(request)
    if participant is None:
        return JsonResponse({"error": "Private Kiosk-Anmeldung erforderlich."}, status=403)
    return _subscribe(request, participant, participant_owner=True)


def _revoke(request: HttpRequest, owner: Any, subscription_id: int, *, participant_owner: bool) -> JsonResponse:
    subscription = get_object_or_404(PushSubscription, pk=subscription_id, **_owner_filter(owner, participant_owner))
    subscription.delete()
    return JsonResponse({}, status=204)


@login_required
@require_POST
def notification_revoke(request: HttpRequest, subscription_id: int) -> JsonResponse:
    """Revoke one push device owned by the current user."""
    return _revoke(request, request.user, subscription_id, participant_owner=False)


@require_POST
def kiosk_notification_revoke(request: HttpRequest, subscription_id: int) -> JsonResponse:
    """Revoke one push device owned by the private participant."""
    participant = _private_participant(request)
    if participant is None:
        return JsonResponse({"error": "Private Kiosk-Anmeldung erforderlich."}, status=403)
    return _revoke(request, participant, subscription_id, participant_owner=True)


def _rename(
    owner: Any,
    subscription_id: int,
    payload: dict[str, Any] | None,
    *,
    participant_owner: bool,
) -> JsonResponse:
    subscription = get_object_or_404(
        PushSubscription,
        pk=subscription_id,
        **_owner_filter(owner, participant_owner),
    )
    device_name = _device_name(payload)
    if device_name is None:
        return JsonResponse({"error": "Ungültiger Gerätename."}, status=400)
    subscription.device_name = device_name
    subscription.save(update_fields=["device_name", "updated_at"])
    return JsonResponse({"device": _device_payload(subscription)})


@login_required
@require_POST
def notification_rename(request: HttpRequest, subscription_id: int) -> JsonResponse:
    """Rename one push device owned by the current user."""
    return _rename(request.user, subscription_id, _json_payload(request), participant_owner=False)


@require_POST
def kiosk_notification_rename(request: HttpRequest, subscription_id: int) -> JsonResponse:
    """Rename one push device owned by the private participant."""
    participant = _private_participant(request)
    if participant is None:
        return JsonResponse({"error": "Private Kiosk-Anmeldung erforderlich."}, status=403)
    return _rename(participant, subscription_id, _json_payload(request), participant_owner=True)


def _update_preferences(
    owner: Any,
    subscription_id: int,
    payload: dict[str, Any] | None,
    *,
    participant_owner: bool,
) -> JsonResponse:
    subscription = get_object_or_404(
        PushSubscription,
        pk=subscription_id,
        **_owner_filter(owner, participant_owner),
    )
    categories = _category_selection(
        payload,
        allowed_categories(participant_owner=participant_owner),
    )
    if categories is None:
        return JsonResponse({"error": "Ungültige Benachrichtigungskategorie."}, status=400)
    subscription.categories = categories
    subscription.save(update_fields=["categories", "updated_at"])
    return JsonResponse({"device": _device_payload(subscription)})


@login_required
@require_POST
def notification_preferences(request: HttpRequest, subscription_id: int) -> JsonResponse:
    """Update notification categories for one push device owned by the current user."""
    return _update_preferences(
        request.user,
        subscription_id,
        _json_payload(request),
        participant_owner=False,
    )


@require_POST
def kiosk_notification_preferences(request: HttpRequest, subscription_id: int) -> JsonResponse:
    """Update notification categories for one push device owned by the private participant."""
    participant = _private_participant(request)
    if participant is None:
        return JsonResponse({"error": "Private Kiosk-Anmeldung erforderlich."}, status=403)
    return _update_preferences(
        participant,
        subscription_id,
        _json_payload(request),
        participant_owner=True,
    )


def queue_test_notification(owner: Any, *, participant_owner: bool, subscription_id: int) -> None:
    """Queue a harmless test message for one owner-controlled device."""
    subscription = get_object_or_404(PushSubscription, pk=subscription_id, **_owner_filter(owner, participant_owner))
    category = subscription.categories[0]
    kwargs = {
        "category": category,
        "title": "Testbenachrichtigung",
        "body": "Push-Benachrichtigungen sind für dieses Gerät eingerichtet.",
        "target_url": "/kiosk/notifications/" if participant_owner else "/notifications/",
        "dedupe_key": f"test:{subscription.pk}:{int(subscription.updated_at.timestamp())}",
    }
    if participant_owner:
        queue_participant_notification(owner, **kwargs)
    else:
        queue_user_notification(owner, **kwargs)


@login_required
@require_POST
def notification_test(request: HttpRequest, subscription_id: int) -> JsonResponse:
    """Queue a test message for one push device owned by the current user."""
    queue_test_notification(request.user, participant_owner=False, subscription_id=subscription_id)
    return JsonResponse({}, status=202)


@require_POST
def kiosk_notification_test(request: HttpRequest, subscription_id: int) -> JsonResponse:
    """Queue a test message for one push device owned by the private participant."""
    participant = _private_participant(request)
    if participant is None:
        return JsonResponse({"error": "Private Kiosk-Anmeldung erforderlich."}, status=403)
    queue_test_notification(participant, participant_owner=True, subscription_id=subscription_id)
    return JsonResponse({}, status=202)
