"""Secure self-service recovery for administrative passwords and participant PINs."""

from datetime import timedelta
from typing import Any, cast

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
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_post_parameters

from .email_delivery import has_valid_recipient_email, is_email_configuration_usable, queue_account_recovery_email
from .forms import KioskLoginForm, _is_trivial_personal_pin, validate_personal_kiosk_pin
from .kiosk_access import KIOSK_MODE_SESSION_KEY, clear_kiosk_identity_session
from .kiosk_security import _recent_attempts, clear_login_rate_limit, kiosk_client_key
from .models import (
    AccountRecoveryAttempt,
    AccountRecoveryDeliveryRequest,
    AccountRecoveryIdentifierAttempt,
    AccountRecoveryToken,
    EmailConfiguration,
    Participant,
    ParticipantFamilyMember,
)
from .notifications import queue_account_recovery_push
from .recovery_tokens import (
    RECOVERY_TOKEN_PLACEHOLDER,
    create_account_recovery_token,
    find_valid_account_recovery,
    has_usable_recovery_credential,
    invalidate_account_recovery_tokens,
    lock_valid_account_recovery,
    recovery_owner_is_active,
    revoke_owner_recovery_push_subscriptions,
)

User = get_user_model()
GENERIC_RECOVERY_MESSAGE = (
    "Falls ein aktives Konto passt und ein Kontaktweg hinterlegt ist, wurde ein Link zum Zurücksetzen versendet."
)
_IDENTIFIER_BUDGET_KEY = "0" * 64


class AccountRecoveryRequestForm(forms.Form):
    """Collect an administrative account identifier without disclosing matches."""

    identifier = forms.CharField(label="E-Mail-Adresse oder Benutzername", max_length=254, strip=True)


class KioskPinRecoveryRequestForm(forms.Form):
    """Collect a visible kiosk identity or an email address for PIN recovery."""

    participant = forms.ChoiceField(label="Teilnehmer auswählen", required=False)
    email = forms.EmailField(label="Oder E-Mail-Adresse", required=False, max_length=254)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        login_form = KioskLoginForm()
        cast(forms.ChoiceField, self.fields["participant"]).choices = cast(
            forms.ChoiceField, login_form.fields["participant"]
        ).choices

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        participant = cleaned_data.get("participant")
        email = cleaned_data.get("email")
        if participant and email:
            raise forms.ValidationError("Bitte wähle entweder einen Teilnehmer oder gib eine E-Mail-Adresse ein.")
        if not participant and not email:
            raise forms.ValidationError("Bitte wähle einen Teilnehmer aus oder gib eine E-Mail-Adresse ein.")
        cleaned_data["identifier"] = participant or email
        return cleaned_data


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


def _identifier_key(identifier: str) -> str:
    """Return a keyed, irreversible key for a bounded normalized identifier."""
    normalized = identifier.strip().casefold()[:254]
    return salted_hmac(
        "billing.account-recovery-identifier", normalized, secret=settings.SECRET_KEY, algorithm="sha256"
    ).hexdigest()


def _save_recovery_attempt(attempt: Any, timestamps: list[float], *, now: Any) -> None:
    timestamps.append(now.timestamp())
    attempt.request_timestamps = timestamps
    attempt.save(update_fields=["request_timestamps", "updated_at"])


def _consume_recovery_attempt(request: HttpRequest, identifier: str) -> bool:
    """Consume one request from both persistent client and identifier windows."""
    now = timezone.now()
    window_seconds = max(1, int(getattr(settings, "ACCOUNT_RECOVERY_REQUEST_WINDOW_SECONDS", 900)))
    maximum = max(1, int(getattr(settings, "ACCOUNT_RECOVERY_MAX_REQUESTS", 5)))
    cutoff = now.timestamp() - window_seconds
    AccountRecoveryAttempt.objects.filter(updated_at__lt=now - timedelta(seconds=window_seconds)).delete()
    AccountRecoveryIdentifierAttempt.objects.exclude(identifier_key=_IDENTIFIER_BUDGET_KEY).filter(
        updated_at__lt=now - timedelta(seconds=window_seconds)
    ).delete()
    with transaction.atomic():
        attempt, _created = AccountRecoveryAttempt.objects.select_for_update().get_or_create(
            client_key=kiosk_client_key(request)
        )
        recent = _recent_attempts(attempt.request_timestamps, cutoff=cutoff)
        if len(recent) >= maximum:
            return False
        AccountRecoveryIdentifierAttempt.objects.get_or_create(identifier_key=_IDENTIFIER_BUDGET_KEY)
        AccountRecoveryIdentifierAttempt.objects.select_for_update().get(identifier_key=_IDENTIFIER_BUDGET_KEY)
        identifier_key = _identifier_key(identifier)
        identifier_attempt = (
            AccountRecoveryIdentifierAttempt.objects.select_for_update().filter(identifier_key=identifier_key).first()
        )
        if identifier_attempt is None:
            identifier_budget = max(1, int(getattr(settings, "ACCOUNT_RECOVERY_MAX_IDENTIFIER_BUCKETS", 10_000)))
            stored_identifiers = AccountRecoveryIdentifierAttempt.objects.exclude(
                identifier_key=_IDENTIFIER_BUDGET_KEY
            ).count()
            if stored_identifiers >= identifier_budget:
                _save_recovery_attempt(attempt, recent, now=now)
                return False
            identifier_attempt = AccountRecoveryIdentifierAttempt.objects.create(identifier_key=identifier_key)
        identifier_recent = _recent_attempts(identifier_attempt.request_timestamps, cutoff=cutoff)
        identifier_maximum = max(1, int(getattr(settings, "ACCOUNT_RECOVERY_MAX_REQUESTS_PER_IDENTIFIER", maximum)))
        if len(recent) >= maximum or len(identifier_recent) >= identifier_maximum:
            _save_recovery_attempt(attempt, recent, now=now)
            return False
        _save_recovery_attempt(attempt, recent, now=now)
        _save_recovery_attempt(identifier_attempt, identifier_recent, now=now)
    return True


def _kiosk_login_route(kiosk_mode: str) -> str:
    return "central-kiosk-login" if kiosk_mode == AccountRecoveryDeliveryRequest.KioskMode.CENTRAL else "kiosk-login"


def _kiosk_recovery_sent_route(kiosk_mode: str) -> str:
    return (
        "central-kiosk-pin-recovery-sent"
        if kiosk_mode == AccountRecoveryDeliveryRequest.KioskMode.CENTRAL
        else "account-recovery-sent"
    )


def _rate_limited_response(request: HttpRequest, *, kiosk_mode: str = "private") -> HttpResponse:
    response = render(
        request,
        "billing/account_recovery_sent.html",
        {"message": GENERIC_RECOVERY_MESSAGE, "kiosk_login_url": reverse(_kiosk_login_route(kiosk_mode))},
        status=429,
    )
    response["Retry-After"] = str(max(1, int(getattr(settings, "ACCOUNT_RECOVERY_REQUEST_WINDOW_SECONDS", 900))))
    return response


def _has_delivery_channel(owner: Any, *, email_enabled: bool) -> bool:
    email = getattr(owner, "email", "")
    push_owner = owner
    return (email_enabled and bool(email and has_valid_recipient_email(email))) or (
        settings.WEB_PUSH_ENABLED and push_owner.push_subscriptions.filter(is_active=True).exists()
    )


@transaction.atomic
def _deliver_recovery(
    recovery_url: str,
    *,
    owner: Any,
    kind: str,
    subject: str,
    body_intro: str,
    target_path: str | None = None,
    kiosk_mode: str | None = None,
) -> None:
    configuration = EmailConfiguration.load()
    configuration = EmailConfiguration.objects.select_for_update().get(pk=configuration.pk)
    email_enabled = is_email_configuration_usable(configuration)
    if not _has_delivery_channel(owner, email_enabled=email_enabled):
        return
    if kind == AccountRecoveryToken.Kind.PARTICIPANT_PIN:
        owner = Participant.objects.select_for_update().get(pk=owner.pk)
    elif kind == AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN:
        owner = (
            ParticipantFamilyMember.objects.select_related("guardian", "guardian__camp")
            .select_for_update()
            .get(pk=owner.pk)
        )
    elif kind == AccountRecoveryToken.Kind.USER_PASSWORD:
        owner = User.objects.select_for_update().get(pk=owner.pk)
    else:
        raise ValueError("Unsupported account-recovery kind")
    if not recovery_owner_is_active(kind, owner):
        return
    if not has_usable_recovery_credential(kind, owner):
        return
    invalidate_account_recovery_tokens(kind=kind, owner=owner)
    target_path = target_path or reverse("account-recovery-confirm", kwargs={"token": RECOVERY_TOKEN_PLACEHOLDER})
    if kind == AccountRecoveryToken.Kind.USER_PASSWORD:
        name = owner.get_full_name() or owner.get_username()
    else:
        name = owner.full_name
    camp = owner.guardian.camp if kind == AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN else getattr(owner, "camp", None)
    email = getattr(owner, "email", "")
    if email_enabled and email and has_valid_recipient_email(email):
        recovery = create_account_recovery_token(kind=kind, owner=owner, kiosk_mode=kiosk_mode)
        queue_account_recovery_email(
            recipient_email=email,
            recipient_name=name,
            subject=subject,
            body=(f"{body_intro}\n\nDer Link ist zeitlich begrenzt und kann einmal verwendet werden.\n{recovery_url}"),
            camp=camp,
            account_recovery=recovery,
        )
    queue_account_recovery_push(
        owner,
        kind=kind,
        title=subject,
        body="Öffne diesen zeitlich begrenzten Link, um neue Zugangsdaten festzulegen.",
        target_url=target_path,
        kiosk_mode=kiosk_mode,
    )


def _render_request_form(request: HttpRequest, *, form: forms.Form, title: str) -> HttpResponse:
    return render(request, "billing/account_recovery_request.html", {"form": form, "title": title})


def account_recovery_request(request: HttpRequest) -> HttpResponse:
    """Accept an admin-interface identifier while returning a non-enumerating response."""
    form = AccountRecoveryRequestForm(request.POST or None)
    if request.method != "POST" or not form.is_valid():
        return _render_request_form(request, form=form, title="Passwort zurücksetzen")
    identifier = form.cleaned_data["identifier"]
    if not _consume_recovery_attempt(request, identifier):
        return _rate_limited_response(request)

    AccountRecoveryDeliveryRequest.objects.create(
        identifier=identifier,
        kind=AccountRecoveryDeliveryRequest.Kind.USER_PASSWORD,
    )
    return redirect("account-recovery-sent")


def send_due_account_recovery_requests(*, batch_size: int = 25) -> int:
    """Resolve durable public requests outside the HTTP response path."""
    now = timezone.now()
    AccountRecoveryDeliveryRequest.objects.filter(
        status=AccountRecoveryDeliveryRequest.Status.PROCESSING,
        processing_started_at__lt=now - timedelta(minutes=15),
    ).update(status=AccountRecoveryDeliveryRequest.Status.PENDING, processing_started_at=None)
    request_ids = list(
        AccountRecoveryDeliveryRequest.objects.filter(status=AccountRecoveryDeliveryRequest.Status.PENDING)
        .order_by("created_at", "pk")
        .values_list("pk", flat=True)[:batch_size]
    )
    delivered = 0
    for request_id in request_ids:
        with transaction.atomic():
            claimed = AccountRecoveryDeliveryRequest.objects.filter(
                pk=request_id, status=AccountRecoveryDeliveryRequest.Status.PENDING
            ).update(status=AccountRecoveryDeliveryRequest.Status.PROCESSING, processing_started_at=timezone.now())
            if not claimed:
                continue
            job = AccountRecoveryDeliveryRequest.objects.select_for_update().get(pk=request_id)
            if job.kind == AccountRecoveryDeliveryRequest.Kind.USER_PASSWORD:
                target_path = reverse("account-recovery-confirm", kwargs={"token": RECOVERY_TOKEN_PLACEHOLDER})
                recovery_url = f"{settings.ACCOUNT_RECOVERY_PUBLIC_ORIGIN}{target_path}"
                users: QuerySet[Any] = User.objects.filter(is_active=True).filter(
                    Q(username__iexact=job.identifier) | Q(email__iexact=job.identifier)
                )
                for user in users.order_by("pk")[:10]:
                    _deliver_recovery(
                        recovery_url,
                        owner=user,
                        kind=AccountRecoveryToken.Kind.USER_PASSWORD,
                        subject="Passwort zurücksetzen",
                        body_intro=(
                            "Für das Fliegerlager-Administrationskonto "
                            f"{user.get_username()} wurde ein neues Passwort angefordert."
                        ),
                    )
            elif job.kind in {
                AccountRecoveryDeliveryRequest.Kind.KIOSK_PIN_EMAIL,
                AccountRecoveryDeliveryRequest.Kind.KIOSK_PIN_PICKER,
            }:
                _deliver_kiosk_recovery(
                    job.identifier,
                    picker=job.kind == AccountRecoveryDeliveryRequest.Kind.KIOSK_PIN_PICKER,
                    kiosk_mode=job.kiosk_mode,
                )
            else:
                raise ValueError("Unsupported account-recovery request kind")
            job.delete()
            delivered += 1
    return delivered


def _deliver_kiosk_recovery(identifier: str, *, picker: bool, kiosk_mode: str) -> None:
    """Resolve one queued kiosk request and enqueue its recovery channels."""
    if picker and identifier.startswith("participant-"):
        participants = (
            Participant.objects.filter(
                pk=int(identifier.removeprefix("participant-")),
                camp__is_active=True,
                archived_at__isnull=True,
            )
            .exclude(status=Participant.Status.PENDING_APPROVAL)
            .select_related("camp")
        )
        family_members = ParticipantFamilyMember.objects.none()
    elif picker and identifier.startswith("family-"):
        participants = Participant.objects.none()
        family_members = (
            ParticipantFamilyMember.objects.filter(
                pk=int(identifier.removeprefix("family-")),
                guardian__camp__is_active=True,
                guardian__archived_at__isnull=True,
                role=ParticipantFamilyMember.Role.COMPANION,
                is_active=True,
            )
            .exclude(guardian__status=Participant.Status.PENDING_APPROVAL)
            .select_related("guardian", "guardian__camp")
        )
    else:
        participants = (
            Participant.objects.filter(
                email__iexact=identifier,
                camp__is_active=True,
                archived_at__isnull=True,
            )
            .exclude(status=Participant.Status.PENDING_APPROVAL)
            .select_related("camp")
            .order_by("pk")
        )
        family_members = (
            ParticipantFamilyMember.objects.filter(
                email__iexact=identifier,
                guardian__camp__is_active=True,
                guardian__archived_at__isnull=True,
                role=ParticipantFamilyMember.Role.COMPANION,
                is_active=True,
            )
            .exclude(guardian__status=Participant.Status.PENDING_APPROVAL)
            .select_related("guardian", "guardian__camp")
            .order_by("pk")
        )
    confirm_route = (
        "central-kiosk-pin-recovery-confirm"
        if kiosk_mode == AccountRecoveryDeliveryRequest.KioskMode.CENTRAL
        else "account-recovery-confirm"
    )
    target_path = reverse(confirm_route, kwargs={"token": RECOVERY_TOKEN_PLACEHOLDER})
    recovery_url = f"{settings.ACCOUNT_RECOVERY_PUBLIC_ORIGIN}{target_path}"
    for participant in participants:
        _deliver_recovery(
            recovery_url,
            owner=participant,
            kind=AccountRecoveryToken.Kind.PARTICIPANT_PIN,
            subject="PIN zurücksetzen",
            body_intro=(
                f"Für das Kiosk-Konto {participant.full_name} im Fliegerlager {participant.camp.name} "
                "wurde eine neue PIN angefordert."
            ),
            target_path=target_path,
            kiosk_mode=kiosk_mode,
        )
    for family_member in family_members:
        _deliver_recovery(
            recovery_url,
            owner=family_member,
            kind=AccountRecoveryToken.Kind.FAMILY_MEMBER_PIN,
            subject="PIN zurücksetzen",
            body_intro=(
                f"Für das Kiosk-Konto {family_member.full_name} im Fliegerlager "
                f"{family_member.guardian.camp.name} wurde eine neue PIN angefordert."
            ),
            target_path=target_path,
            kiosk_mode=kiosk_mode,
        )


def kiosk_pin_recovery_request(request: HttpRequest, kiosk_mode: str = "private") -> HttpResponse:
    """Accept a visible kiosk identity or email while returning a non-enumerating response."""
    form = KioskPinRecoveryRequestForm(request.POST or None)
    if request.method != "POST":
        return _render_request_form(request, form=form, title="PIN zurücksetzen")
    if not form.is_valid():
        invalid_participant = form.errors.as_data().get("participant", [])
        if any(error.code == "invalid_choice" for error in invalid_participant):
            return redirect(_kiosk_recovery_sent_route(kiosk_mode))
        return _render_request_form(request, form=form, title="PIN zurücksetzen")
    identifier = form.cleaned_data["identifier"]
    if not _consume_recovery_attempt(request, identifier):
        return _rate_limited_response(request, kiosk_mode=kiosk_mode)
    AccountRecoveryDeliveryRequest.objects.create(
        identifier=identifier,
        kind=(
            AccountRecoveryDeliveryRequest.Kind.KIOSK_PIN_PICKER
            if form.cleaned_data.get("participant")
            else AccountRecoveryDeliveryRequest.Kind.KIOSK_PIN_EMAIL
        ),
        kiosk_mode=kiosk_mode,
    )
    return redirect(_kiosk_recovery_sent_route(kiosk_mode))


def account_recovery_sent(request: HttpRequest, kiosk_mode: str = "private") -> HttpResponse:
    """Render the same completion response for matching and unknown identifiers."""
    return render(
        request,
        "billing/account_recovery_sent.html",
        {"message": GENERIC_RECOVERY_MESSAGE, "kiosk_login_url": reverse(_kiosk_login_route(kiosk_mode))},
    )


def _invalid_token_response(request: HttpRequest) -> HttpResponse:
    return _protect_token_response(render(request, "billing/account_recovery_invalid.html", status=400))


def _protect_token_response(response: HttpResponse) -> HttpResponse:
    """Prevent recovery URLs from entering caches or same-origin referrer headers."""
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@sensitive_post_parameters("new_password1", "new_password2", "pin", "pin_repeat")
def account_recovery_confirm(request: HttpRequest, token: str, kiosk_mode: str = "private") -> HttpResponse:
    """Consume one valid recovery token after a replacement credential passes validation."""
    recovery = find_valid_account_recovery(token)
    if recovery is None:
        return _invalid_token_response(request)
    if recovery.kind != AccountRecoveryToken.Kind.USER_PASSWORD and recovery.kiosk_mode != kiosk_mode:
        return _invalid_token_response(request)
    if kiosk_mode == AccountRecoveryDeliveryRequest.KioskMode.CENTRAL:
        clear_kiosk_identity_session(request)
        request.session[KIOSK_MODE_SESSION_KEY] = kiosk_mode
        request.session.set_expiry(120)
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
        locked_result = lock_valid_account_recovery(recovery.pk, token)
        if locked_result is None:
            return _invalid_token_response(request)
        locked_recovery, owner = locked_result
        if locked_recovery.kind == AccountRecoveryToken.Kind.USER_PASSWORD:
            assert isinstance(form, SetPasswordForm)
            user = owner
            user.set_password(form.cleaned_data["new_password1"])
            user.save(update_fields=["password"])
            revoke_owner_recovery_push_subscriptions(kind=locked_recovery.kind, owner=user)
            clear_login_rate_limit(user.get_username(), request=request, additional_usernames=(user.email,))
            success_message = "Passwort wurde geändert. Du kannst dich jetzt anmelden."
            destination = "login"
        elif locked_recovery.kind == AccountRecoveryToken.Kind.PARTICIPANT_PIN:
            owner.pin.set_pin(form.cleaned_data["pin"])
            owner.pin.save()
            revoke_owner_recovery_push_subscriptions(kind=locked_recovery.kind, owner=owner)
            success_message = "PIN wurde geändert. Du kannst dich jetzt anmelden."
            destination = _kiosk_login_route(kiosk_mode)
        else:
            owner.pin.set_pin(form.cleaned_data["pin"])
            owner.pin.save()
            revoke_owner_recovery_push_subscriptions(kind=locked_recovery.kind, owner=owner)
            success_message = "PIN wurde geändert. Du kannst dich jetzt anmelden."
            destination = _kiosk_login_route(kiosk_mode)
        locked_recovery.used_at = timezone.now()
        locked_recovery.save(update_fields=["used_at", "updated_at"])
    messages.success(request, success_message)
    return _protect_token_response(redirect(destination))
