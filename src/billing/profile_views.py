"""Isolated kiosk profile workflows awaiting URL integration."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render

from .kiosk_access import KIOSK_FAMILY_MEMBER_SESSION_KEY
from .models import KioskActionAuditLog, Participant, ParticipantFamilyMember
from .profile_forms import ParticipantFamilyMemberProfileForm, ParticipantProfileForm
from .services import create_kiosk_action_audit_log
from .views import _activate_kiosk_mode, _kiosk_context, _kiosk_family_member, _kiosk_participant, _kiosk_route


def _profile_context(
    *,
    participant: Participant,
    form: Any,
    kiosk_mode: str,
    managed_family_members: list[ParticipantFamilyMember],
) -> dict[str, Any]:
    """Build the minimal presentational context shared by profile endpoints."""
    return {
        **_kiosk_context(kiosk_mode),
        "participant": participant,
        "form": form,
        "managed_family_members": managed_family_members,
    }


def _active_identity(
    request: HttpRequest, kiosk_mode: str
) -> tuple[Participant, ParticipantFamilyMember | None] | None:
    """Resolve the existing kiosk identity, rejecting stale companion session state."""
    _activate_kiosk_mode(request, kiosk_mode)
    participant = _kiosk_participant(request)
    if participant is None:
        return None
    family_member = _kiosk_family_member(request, participant)
    if request.session.get(KIOSK_FAMILY_MEMBER_SESSION_KEY) and family_member is None:
        return None
    return participant, family_member


def _profile_audit(
    *,
    actor: Participant,
    actor_family_member: ParticipantFamilyMember | None,
    target_participant: Participant,
    target_family_member: ParticipantFamilyMember | None,
    changed_fields: list[str],
) -> None:
    """Record a profile change without storing contact values or secrets in the audit trail."""
    field_snapshot = {"changed_fields": changed_fields}
    create_kiosk_action_audit_log(
        camp=actor.camp,
        actor_participant=actor,
        actor_family_member=actor_family_member,
        target_participant=target_participant,
        target_family_member=target_family_member,
        action=KioskActionAuditLog.Action.PROFILE_UPDATED,
        description="Stammdaten im Kiosk geändert.",
        before=field_snapshot,
        after=field_snapshot,
    )


def kiosk_profile(request: HttpRequest, participant_id: int, kiosk_mode: str = "private") -> HttpResponse:
    """Render or update the authenticated primary participant's own profile only."""
    identity = _active_identity(request, kiosk_mode)
    if identity is None:
        return redirect(_kiosk_route(kiosk_mode, "login"))
    actor, actor_family_member = identity
    if actor_family_member is not None or actor.pk != participant_id:
        return HttpResponseForbidden("Dieses Profil darf nicht bearbeitet werden.")

    with transaction.atomic():
        participant = (
            Participant.objects.select_for_update()
            .select_related("camp")
            .filter(pk=actor.pk, camp__is_active=True, archived_at__isnull=True)
            .first()
        )
        if participant is None:
            return redirect(_kiosk_route(kiosk_mode, "login"))
        form = ParticipantProfileForm(request.POST or None, instance=participant)
        if request.method == "POST" and form.is_valid():
            changed_fields = form.changed_field_names
            form.save()
            if changed_fields:
                _profile_audit(
                    actor=participant,
                    actor_family_member=None,
                    target_participant=participant,
                    target_family_member=None,
                    changed_fields=changed_fields,
                )
            return redirect(_kiosk_route(kiosk_mode, "home"))

    return render(
        request,
        "billing/kiosk_profile.html",
        _profile_context(
            participant=actor,
            form=form,
            kiosk_mode=kiosk_mode,
            managed_family_members=list(
                actor.family_members.filter(
                    is_active=True,
                    role=ParticipantFamilyMember.Role.CHILD,
                ).order_by("last_name", "first_name", "pk")
            ),
        ),
        status=400 if request.method == "POST" else 200,
    )


def kiosk_family_member_profile(
    request: HttpRequest, family_member_id: int, kiosk_mode: str = "private"
) -> HttpResponse:
    """Render or update a companion's own or a guardian's own family-member profile."""
    identity = _active_identity(request, kiosk_mode)
    if identity is None:
        return redirect(_kiosk_route(kiosk_mode, "login"))
    actor, actor_family_member = identity

    with transaction.atomic():
        locked_actor = (
            Participant.objects.select_for_update()
            .select_related("camp")
            .filter(pk=actor.pk, camp__is_active=True, archived_at__isnull=True)
            .first()
        )
        if locked_actor is None:
            return redirect(_kiosk_route(kiosk_mode, "login"))
        target = (
            ParticipantFamilyMember.objects.select_for_update()
            .select_related("guardian", "guardian__camp")
            .filter(pk=family_member_id, guardian=locked_actor, guardian__camp__is_active=True, is_active=True)
            .first()
        )
        if target is None or (actor_family_member is not None and target.pk != actor_family_member.pk):
            return HttpResponseForbidden("Dieses Familienprofil darf nicht bearbeitet werden.")
        if actor_family_member is None and target.role != ParticipantFamilyMember.Role.CHILD:
            return HttpResponseForbidden("Dieses Familienprofil darf nicht bearbeitet werden.")
        if actor_family_member is not None and target.role != ParticipantFamilyMember.Role.COMPANION:
            return HttpResponseForbidden("Dieses Familienprofil darf nicht bearbeitet werden.")

        form = ParticipantFamilyMemberProfileForm(request.POST or None, instance=target)
        if request.method == "POST" and form.is_valid():
            changed_fields = form.changed_field_names
            form.save()
            if changed_fields:
                _profile_audit(
                    actor=locked_actor,
                    actor_family_member=actor_family_member,
                    target_participant=locked_actor,
                    target_family_member=target,
                    changed_fields=changed_fields,
                )
            return redirect(_kiosk_route(kiosk_mode, "home"))

    return render(
        request,
        "billing/kiosk_profile.html",
        _profile_context(
            participant=actor,
            form=form,
            kiosk_mode=kiosk_mode,
            managed_family_members=[target],
        ),
        status=400 if request.method == "POST" else 200,
    )
