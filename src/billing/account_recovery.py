"""Secure self-service recovery for administrative passwords and participant PINs."""

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .email_delivery import has_valid_recipient_email, queue_account_recovery_email
from .forms import _is_trivial_personal_pin, validate_personal_kiosk_pin
from .kiosk_security import _recent_attempts, clear_login_rate_limit, kiosk_client_key
from .models import AccountRecoveryAttempt, AccountRecoveryToken, Participant
from .notifications import queue_account_recovery_push

User = get_user_model()
GENERIC_RECOVERY_MESSAGE = (
    "Falls ein aktives Konto passt und ein Kontaktweg hinterlegt ist, wurde ein Link zum Zurücksetzen versendet."
)


class AccountRecoveryRequestForm(forms.Form):
    """Collect an administrative account identifier without disclosing matches."""

    identifier = forms.CharField(label="E-Mail-Adresse oder Benutzername", max_length=254, strip=True)


class KioskPinRecoveryRequestForm(forms.Form):
    """Collect the address associated with a participant kiosk account."""

    email = forms.EmailField(label="E-Mail-Adresse", max_length=254)


class RecoveryPinForm(forms.Form):
    """Validate a replacement participant PIN without requiring the forgotten PIN."""

    pin = forms.CharField(
        label="Neue PIN",
        strip=True,
        validators=[validate_personal_kiosk_pin],
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password", "inputmode": "numeric", "minlength": "4", "maxlength": "10"}
        ),
    )
    pin_repeat = forms.CharField(
        label="Neue PIN wiederholen",
        strip=True,
        validators=[validate_personal_kiosk_pin],
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password", "inputmode": "numeric", "minlength": "4", "maxlength": "10"}
        ),
    )

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        pin = cleaned_data.get("pin")
        pin_repeat = cleaned_data.get("pin_repeat")
        if pin and pin_repeat and pin != pin_repeat:
            self.add_error("pin_repeat", "Die PINs stimmen nicht überein.")
        if pin and _is_trivial_personal_pin(pin):
            self.add_error("pin", "Bitte wähle eine sicherere PIN ohne einfache Zahlenfolge.")
        return cleaned_data


def _token_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _token_timeout() -> timedelta:
    timeout_seconds = max(1, int(getattr(settings, "ACCOUNT_RECOVERY_TIMEOUT_SECONDS", 3600)))
    return timedelta(seconds=timeout_seconds)


def _consume_recovery_attempt(request: HttpRequest) -> bool:
    """Consume one request from a persistent per-client sliding window."""
    now = timezone.now()
    window_seconds = max(1, int(getattr(settings, "ACCOUNT_RECOVERY_REQUEST_WINDOW_SECONDS", 900)))
    maximum = max(1, int(getattr(settings, "ACCOUNT_RECOVERY_MAX_REQUESTS", 5)))
    cutoff = now.timestamp() - window_seconds
    AccountRecoveryAttempt.objects.filter(updated_at__lt=now - timedelta(seconds=window_seconds)).delete()
    with transaction.atomic():
        attempt, _created = AccountRecoveryAttempt.objects.select_for_update().get_or_create(
            client_key=kiosk_client_key(request)
        )
        recent = _recent_attempts(attempt.request_timestamps, cutoff=cutoff)
        if len(recent) >= maximum:
            return False
        recent.append(now.timestamp())
        attempt.request_timestamps = recent
        attempt.save(update_fields=["request_timestamps", "updated_at"])
    return True


def _rate_limited_response(request: HttpRequest) -> HttpResponse:
    response = render(
        request,
        "billing/account_recovery_sent.html",
        {"message": GENERIC_RECOVERY_MESSAGE},
        status=429,
    )
    response["Retry-After"] = str(max(1, int(getattr(settings, "ACCOUNT_RECOVERY_REQUEST_WINDOW_SECONDS", 900))))
    return response


@transaction.atomic
def _issue_token(*, kind: str, owner: Any) -> tuple[AccountRecoveryToken, str]:
    """Invalidate earlier links and return a newly persisted hashed token plus its raw secret."""
    now = timezone.now()
    owner_filter = {"participant": owner} if kind == AccountRecoveryToken.Kind.PARTICIPANT_PIN else {"user": owner}
    AccountRecoveryToken.objects.filter(kind=kind, used_at__isnull=True, **owner_filter).update(used_at=now)
    raw_token = secrets.token_urlsafe(32)
    recovery = AccountRecoveryToken.objects.create(
        kind=kind,
        token_digest=_token_digest(raw_token),
        expires_at=now + _token_timeout(),
        **owner_filter,
    )
    return recovery, raw_token


def _has_delivery_channel(owner: Any) -> bool:
    email = getattr(owner, "email", "")
    return bool(email and has_valid_recipient_email(email)) or (
        settings.WEB_PUSH_ENABLED and owner.push_subscriptions.filter(is_active=True).exists()
    )


@transaction.atomic
def _deliver_recovery(
    request: HttpRequest,
    *,
    owner: Any,
    participant_owner: bool,
    subject: str,
    body_intro: str,
) -> None:
    kind = AccountRecoveryToken.Kind.PARTICIPANT_PIN if participant_owner else AccountRecoveryToken.Kind.USER_PASSWORD
    if not _has_delivery_channel(owner):
        return
    if participant_owner:
        owner = Participant.objects.select_for_update().get(pk=owner.pk)
    else:
        owner = User.objects.select_for_update().get(pk=owner.pk)
    recovery, raw_token = _issue_token(kind=kind, owner=owner)
    target_path = reverse("account-recovery-confirm", kwargs={"token": raw_token})
    name = owner.full_name if participant_owner else owner.get_full_name() or owner.get_username()
    email = getattr(owner, "email", "")
    if email and has_valid_recipient_email(email):
        queue_account_recovery_email(
            recipient_email=email,
            recipient_name=name,
            subject=subject,
            body=(
                f"{body_intro}\n\nDer Link ist zeitlich begrenzt und kann einmal verwendet werden.\n"
                f"{request.build_absolute_uri(target_path)}"
            ),
            camp=owner.camp if participant_owner else None,
        )
    queue_account_recovery_push(
        owner,
        participant_owner=participant_owner,
        title=subject,
        body="Öffne diesen zeitlich begrenzten Link, um neue Zugangsdaten festzulegen.",
        target_url=target_path,
        dedupe_key=f"account-recovery:{recovery.pk}",
    )


def _render_request_form(request: HttpRequest, *, form: forms.Form, title: str) -> HttpResponse:
    return render(request, "billing/account_recovery_request.html", {"form": form, "title": title})


def account_recovery_request(request: HttpRequest) -> HttpResponse:
    """Accept an admin-interface identifier while returning a non-enumerating response."""
    form = AccountRecoveryRequestForm(request.POST or None)
    if request.method != "POST" or not form.is_valid():
        return _render_request_form(request, form=form, title="Passwort zurücksetzen")
    if not _consume_recovery_attempt(request):
        return _rate_limited_response(request)

    identifier = form.cleaned_data["identifier"]
    users: QuerySet[Any] = User.objects.filter(is_active=True).filter(
        Q(username__iexact=identifier) | Q(email__iexact=identifier)
    )
    for user in users.order_by("pk")[:10]:
        _deliver_recovery(
            request,
            owner=user,
            participant_owner=False,
            subject="Passwort zurücksetzen",
            body_intro="Für dein Fliegerlager-Administrationskonto wurde ein neues Passwort angefordert.",
        )
    return redirect("account-recovery-sent")


def kiosk_pin_recovery_request(request: HttpRequest) -> HttpResponse:
    """Accept a participant email address while returning a non-enumerating response."""
    form = KioskPinRecoveryRequestForm(request.POST or None)
    if request.method != "POST" or not form.is_valid():
        return _render_request_form(request, form=form, title="PIN zurücksetzen")
    if not _consume_recovery_attempt(request):
        return _rate_limited_response(request)

    participants = (
        Participant.objects.filter(
            email__iexact=form.cleaned_data["email"],
            camp__is_active=True,
            archived_at__isnull=True,
        )
        .exclude(status=Participant.Status.PENDING_APPROVAL)
        .select_related("camp")
        .order_by("pk")[:10]
    )
    for participant in participants:
        _deliver_recovery(
            request,
            owner=participant,
            participant_owner=True,
            subject="PIN zurücksetzen",
            body_intro=f"Für dein Kiosk-Konto im Fliegerlager {participant.camp.name} wurde eine neue PIN angefordert.",
        )
    return redirect("account-recovery-sent")


def account_recovery_sent(request: HttpRequest) -> HttpResponse:
    """Render the same completion response for matching and unknown identifiers."""
    return render(request, "billing/account_recovery_sent.html", {"message": GENERIC_RECOVERY_MESSAGE})


def _valid_recovery(raw_token: str, *, lock: bool = False) -> AccountRecoveryToken | None:
    if lock:
        queryset = AccountRecoveryToken.objects.select_for_update(of=("self",))
    else:
        queryset = AccountRecoveryToken.objects.select_related("user", "participant", "participant__camp")
    recovery = queryset.filter(token_digest=_token_digest(raw_token), used_at__isnull=True).first()
    if recovery is None or recovery.expires_at <= timezone.now():
        return None
    if recovery.user_id is not None:
        user = recovery.user
        if user is None or not user.is_active:
            return None
    if recovery.participant_id is not None:
        participant = recovery.participant
        if participant is None or participant.archived_at is not None or not participant.camp.is_active:
            return None
    return recovery


def _invalid_token_response(request: HttpRequest) -> HttpResponse:
    return _protect_token_response(render(request, "billing/account_recovery_invalid.html", status=400))


def _protect_token_response(response: HttpResponse) -> HttpResponse:
    """Prevent recovery URLs from entering caches or same-origin referrer headers."""
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


def account_recovery_confirm(request: HttpRequest, token: str) -> HttpResponse:
    """Consume one valid recovery token after a replacement credential passes validation."""
    recovery = _valid_recovery(token)
    if recovery is None:
        return _invalid_token_response(request)
    if recovery.kind == AccountRecoveryToken.Kind.USER_PASSWORD:
        user = recovery.user
        if user is None:
            return _invalid_token_response(request)
        form: forms.Form = SetPasswordForm(user, request.POST or None)
        title = "Neues Passwort festlegen"
    else:
        form = RecoveryPinForm(request.POST or None)
        title = "Neue PIN festlegen"
    if request.method != "POST" or not form.is_valid():
        return _protect_token_response(
            render(request, "billing/account_recovery_confirm.html", {"form": form, "title": title})
        )

    with transaction.atomic():
        locked_recovery = _valid_recovery(token, lock=True)
        if locked_recovery is None:
            return _invalid_token_response(request)
        if locked_recovery.kind == AccountRecoveryToken.Kind.USER_PASSWORD:
            user = locked_recovery.user
            if user is None:
                return _invalid_token_response(request)
            assert isinstance(form, SetPasswordForm)
            form.save()
            clear_login_rate_limit(user.get_username())
            success_message = "Passwort wurde geändert. Du kannst dich jetzt anmelden."
            destination = "login"
        else:
            participant = locked_recovery.participant
            if participant is None:
                return _invalid_token_response(request)
            participant.pin.set_pin(form.cleaned_data["pin"])
            participant.pin.save()
            success_message = "PIN wurde geändert. Du kannst dich jetzt anmelden."
            destination = "kiosk-login"
        locked_recovery.used_at = timezone.now()
        locked_recovery.save(update_fields=["used_at", "updated_at"])
    messages.success(request, success_message)
    return _protect_token_response(redirect(destination))
