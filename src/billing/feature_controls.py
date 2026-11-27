"""Known participant features and their per-camp overrides."""

from __future__ import annotations

from collections.abc import Mapping

from django.db.models import F
from django.utils import timezone

from .models import Camp, CampFeatureOverride, PushMessage

FEATURE_LABELS: Mapping[str, str] = {
    "profile": "Profil bearbeiten",
    "family": "Familienmitglieder verwalten",
    "partners": "Partnerfunktionen",
    "meals": "Essen buchen",
    "drinks": "Getränke buchen",
    "attendance": "Anwesenheit melden",
    "shifts": "Dienste verwalten",
    "donations": "Spenden buchen",
    "expenses": "Auslagen einreichen",
    "self_registration": "Selbstregistrierung",
    "notifications": "Optionale Benachrichtigungen",
}


def feature_enabled(camp: Camp, feature_id: str) -> bool:
    """Return the stored state for a known feature, defaulting new features on."""
    if feature_id not in FEATURE_LABELS:
        return False
    override = (
        CampFeatureOverride.objects.filter(camp_id=camp.pk, feature_id=feature_id)
        .values_list("enabled", flat=True)
        .first()
    )
    return True if override is None else bool(override)


def feature_states(camp: Camp) -> dict[str, bool]:
    """Return every catalog feature with its effective camp state."""
    states = {feature_id: True for feature_id in FEATURE_LABELS}
    states.update(
        CampFeatureOverride.objects.filter(camp=camp, feature_id__in=FEATURE_LABELS).values_list(
            "feature_id", "enabled"
        )
    )
    return states


def suppress_queued_feature_messages(camp: Camp, feature_ids: set[str]) -> int:
    """Terminally fail queued optional messages when an associated feature is turned off."""
    if not feature_ids:
        return 0
    changed = PushMessage.objects.filter(
        camp=camp,
        feature_id__in=feature_ids,
        status__in=[PushMessage.Status.PENDING, PushMessage.Status.PROCESSING],
    ).update(
        status=PushMessage.Status.FAILED,
        last_error_code="feature_disabled",
        processing_started_at=None,
        attempts=F("attempts") + 1,
        updated_at=timezone.now(),
    )
    return changed
