from typing import Any, cast

from django import forms

from .email_credentials import EmailCredentialError
from .email_delivery import has_valid_recipient_email
from .models import EmailConfiguration


class ManualEmailContentForm(forms.Form):
    subject = forms.CharField(label="Betreff", max_length=160)
    body = forms.CharField(
        label="Nachricht",
        max_length=10_000,
        widget=forms.Textarea(attrs={"rows": 10}),
    )

    def clean_subject(self) -> str:
        subject = self.cleaned_data["subject"].strip()
        if "\r" in subject or "\n" in subject:
            raise forms.ValidationError("Der Betreff darf keinen Zeilenumbruch enthalten.")
        return subject


class InformationEmailForm(ManualEmailContentForm):
    CHANNEL_CHOICES = [
        ("email", "Nur E-Mail"),
        ("push", "Nur Push"),
        ("both", "E-Mail & Push"),
    ]

    channels = forms.ChoiceField(
        label="Versandkanal",
        choices=CHANNEL_CHOICES,
        required=False,
        initial="email",
        widget=forms.RadioSelect,
    )
    show_in_kiosk = forms.BooleanField(
        label="Zusätzlich als Ankündigung im Kiosk anzeigen",
        required=False,
        initial=False,
    )
    participants = forms.MultipleChoiceField(
        label="Empfänger",
        widget=forms.CheckboxSelectMultiple,
    )

    def clean_channels(self) -> str:
        return self.cleaned_data.get("channels") or "email"

    def __init__(self, *args: Any, camp: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        participants = camp.participants.filter(
            archived_at__isnull=True,
        ).order_by("last_name", "first_name", "pk")
        participant_field = cast(forms.MultipleChoiceField, self.fields["participants"])
        participant_field.choices = [
            (str(participant.pk), f"{participant.full_name} · {participant.email}")
            for participant in participants
            if has_valid_recipient_email(participant.email)
        ]


class SettlementEmailForm(ManualEmailContentForm):
    settlements = forms.MultipleChoiceField(
        label="Rechnungen",
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args: Any, run: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        settlements = run.settlements.select_related("participant").order_by("participant_name", "pk")
        settlement_field = cast(forms.MultipleChoiceField, self.fields["settlements"])
        settlement_field.choices = [
            (
                str(settlement.pk),
                f"{settlement.participant_name} · {settlement.participant.email}",
            )
            for settlement in settlements
            if has_valid_recipient_email(settlement.participant.email)
        ]


class EmailConfigurationForm(forms.ModelForm):
    """Edit the singleton SMTP configuration without exposing its stored password."""

    port = forms.IntegerField(label="SMTP-Port", min_value=1, max_value=65535)
    password = forms.CharField(
        label="SMTP-Passwort",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Leer lassen, um das gespeicherte Passwort beizubehalten.",
    )
    timeout = forms.IntegerField(label="Zeitlimit in Sekunden", min_value=1, max_value=60)
    test_recipient = forms.EmailField(
        label="Empfänger der Test-E-Mail",
        required=False,
        help_text="Wird ausschließlich verwendet, wenn eine Test-E-Mail gesendet wird.",
    )

    class Meta:
        model = EmailConfiguration
        fields = [
            "enabled",
            "host",
            "port",
            "username",
            "password",
            "security",
            "from_name",
            "from_email",
            "reply_to",
            "timeout",
        ]
        labels = {
            "enabled": "E-Mail-Versand aktivieren",
            "host": "SMTP-Host",
            "username": "SMTP-Benutzername",
            "security": "Transportverschlüsselung",
            "from_name": "Absendername",
            "from_email": "Absenderadresse",
            "reply_to": "Antwortadresse",
        }

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        if not cleaned_data.get("enabled"):
            return cleaned_data
        for field_name in ("host", "from_email"):
            if not cleaned_data.get(field_name):
                self.add_error(field_name, "Dieses Feld ist bei aktiviertem Versand erforderlich.")
        if not cleaned_data.get("password"):
            if not self.instance.password_encrypted:
                self.add_error("password", "Für den aktivierten Versand ist ein SMTP-Passwort erforderlich.")
            else:
                try:
                    self.instance.get_password()
                except EmailCredentialError:
                    self.add_error(
                        "password",
                        "Das gespeicherte Passwort ist nicht mehr gültig. Bitte ein neues SMTP-Passwort eingeben.",
                    )
        return cleaned_data

    def clean_from_name(self) -> str:
        from_name = self.cleaned_data["from_name"].strip()
        if "\r" in from_name or "\n" in from_name:
            raise forms.ValidationError("Der Absendername darf keinen Zeilenumbruch enthalten.")
        return from_name

    def save(self, commit: bool = True, *, updated_by: Any | None = None) -> EmailConfiguration:
        configuration = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            configuration.set_password(password)
        if updated_by is not None:
            configuration.updated_by = updated_by
        if commit:
            configuration.save()
        return configuration
