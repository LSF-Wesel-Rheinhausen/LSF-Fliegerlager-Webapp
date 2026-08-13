from datetime import date, time, timedelta
from decimal import Decimal
from typing import Any, cast

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import FileExtensionValidator, RegexValidator
from django.db import models, transaction
from django.utils.formats import number_format

from .models import (
    Camp,
    Charge,
    DailySettlementBackupSettings,
    DailyShiftTemplate,
    Expense,
    MealPlanEntry,
    MealSignup,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    ParticipantFamilyMemberPin,
    ParticipantPin,
    Payment,
    PriceRule,
    Shift,
    UserProfile,
)
from .roles import ROLE_ADMIN, ROLE_CHOICES, user_role

PERCENT_PLACES = Decimal("0.01")
MAX_IMPORT_FILE_SIZE = 5 * 1024 * 1024
MAX_RECEIPT_FILE_SIZE = 5 * 1024 * 1024
ALLOWED_RECEIPT_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "heic"}
RECEIPT_CONTENT_TYPES_BY_EXTENSION = {
    "pdf": frozenset({"application/pdf"}),
    "jpg": frozenset({"image/jpeg"}),
    "jpeg": frozenset({"image/jpeg"}),
    "png": frozenset({"image/png"}),
    "heic": frozenset({"image/heic", "image/heif"}),
}
HEIC_BRANDS = frozenset(
    {
        b"heic",
        b"heix",
        b"hevc",
        b"hevx",
        b"heim",
        b"heis",
        b"hevm",
        b"hevs",
    }
)
RECEIPT_HEADER_SIZE = 64
MAX_HEIF_FTYP_BOX_SIZE = 4096
validate_kiosk_camp_pin = RegexValidator(
    regex=r"\A[0-9]{6,12}\Z",
    message="Die Lager-PIN muss aus 6 bis 12 Ziffern bestehen.",
    code="invalid_kiosk_camp_pin",
)
validate_personal_kiosk_pin = RegexValidator(
    regex=r"\A[0-9]{4,10}\Z",
    message="Die PIN muss aus 4 bis 10 Ziffern bestehen.",
    code="invalid_personal_kiosk_pin",
)
TRIVIAL_PERSONAL_PINS = frozenset(
    {
        "0000",
        "1111",
        "2222",
        "3333",
        "4444",
        "5555",
        "6666",
        "7777",
        "8888",
        "9999",
        "1234",
        "4321",
        "123456",
        "654321",
    }
)


def _is_trivial_personal_pin(pin: str) -> bool:
    """Return whether a personal kiosk PIN is an unsafe repeated or sequential value."""
    return pin in TRIVIAL_PERSONAL_PINS or len(set(pin)) == 1


def _matches_heif_signature(header: bytes) -> bool:
    if len(header) < 16 or header[4:8] != b"ftyp":
        return False

    box_size = int.from_bytes(header[:4], byteorder="big")
    if box_size < 16 or box_size % 4 != 0 or box_size > len(header):
        return False

    brands = {header[8:12]}
    brands.update(header[offset : offset + 4] for offset in range(16, min(box_size, len(header)), 4))
    return not brands.isdisjoint(HEIC_BRANDS)


def _matches_receipt_signature(extension: str, header: bytes) -> bool:
    if extension == "pdf":
        return header.startswith(b"%PDF-")
    if extension in {"jpg", "jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    if extension == "png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == "heic":
        return _matches_heif_signature(header)
    return False


def _read_receipt_header(upload: Any, extension: str) -> bytes:
    try:
        original_position = upload.tell()
        upload.seek(0)
        try:
            header = upload.read(RECEIPT_HEADER_SIZE)
            if extension == "heic" and len(header) >= 8 and header[4:8] == b"ftyp":
                box_size = int.from_bytes(header[:4], byteorder="big")
                if RECEIPT_HEADER_SIZE < box_size <= MAX_HEIF_FTYP_BOX_SIZE:
                    upload.seek(0)
                    header = upload.read(box_size)
        finally:
            upload.seek(original_position)
    except (AttributeError, OSError, ValueError) as error:
        raise ValidationError("Der Rechnungsbeleg konnte nicht gelesen werden.") from error
    if not isinstance(header, bytes):
        raise ValidationError("Der Rechnungsbeleg konnte nicht gelesen werden.")
    return header


def validate_receipt_upload(upload: Any) -> Any:
    """Validate uploaded expense receipts before they reach persistent storage."""
    if not upload:
        return upload

    if upload.size > MAX_RECEIPT_FILE_SIZE:
        raise ValidationError("Der Rechnungsbeleg darf höchstens 5 MB groß sein.")

    extension = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
    if extension not in ALLOWED_RECEIPT_EXTENSIONS:
        raise ValidationError("Erlaubte Dateitypen: PDF, JPG, PNG oder HEIC.")

    raw_content_type = getattr(upload, "content_type", "")
    content_type = str(raw_content_type).lower() if raw_content_type else ""
    if content_type and content_type not in RECEIPT_CONTENT_TYPES_BY_EXTENSION[extension]:
        raise ValidationError("Der Dateityp des Rechnungsbelegs wird nicht unterstützt.")

    if not _matches_receipt_signature(extension, _read_receipt_header(upload, extension)):
        raise ValidationError("Der Dateiinhalt passt nicht zum Dateityp des Rechnungsbelegs.")

    return upload


def subsidy_percentage(value: Decimal) -> Decimal:
    return (value * Decimal("100")).quantize(PERCENT_PLACES)


class SubsidyPercentField(forms.DecimalField):
    """Expose a normalized subsidy rate as a percentage in forms."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("label", "Fördersatz (%)")
        kwargs.setdefault("min_value", 0)
        kwargs.setdefault("max_value", 100)
        kwargs.setdefault("max_digits", 5)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("required", False)
        kwargs.setdefault("widget", forms.NumberInput(attrs={"step": "0.01", "min": "0", "max": "100"}))
        super().__init__(*args, **kwargs)

    def clean(self, value: Any) -> Any:
        percentage = super().clean(value)
        if percentage is None:
            return Decimal("0")
        return percentage / Decimal("100")


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Benutzername oder E-Mail", widget=forms.TextInput(attrs={"autocomplete": "username"})
    )
    password = forms.CharField(
        label="Passwort", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )

    def clean(self):
        from .kiosk_security import check_login_rate_limit, clear_login_rate_limit, consume_login_failure

        raw_username = str(self.data.get("username", ""))
        if self.request and not check_login_rate_limit(self.request, username=raw_username):
            raise ValidationError(
                "Zu viele Fehlversuche. Bitte versuche es in fünf Minuten erneut.",
                code="rate_limited",
            )

        try:
            cleaned_data = super().clean()
            if self.request:
                clear_login_rate_limit(raw_username, request=self.request)
            return cleaned_data
        except ValidationError as e:
            if self.request and e.code == "invalid_login":
                consume_login_failure(self.request, username=raw_username)
            raise


class DailySettlementBackupSettingsForm(forms.ModelForm):
    """Edit the singleton daily settlement backup schedule."""

    class Meta:
        model = DailySettlementBackupSettings
        fields = ["enabled", "run_time"]
        labels = {
            "enabled": "Tägliche Abrechnungs-Backups aktivieren",
            "run_time": "Uhrzeit",
        }
        widgets = {"run_time": forms.TimeInput(attrs={"type": "time"})}


class FirstAdminSetupForm(UserCreationForm):
    username = forms.CharField(label="Benutzername")
    email = forms.EmailField(label="E-Mail-Adresse", required=True)
    password1 = forms.CharField(
        label="Passwort", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    password2 = forms.CharField(
        label="Passwort wiederholen", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    class Meta:
        model = get_user_model()
        fields = ["username", "email"]

    def save(self, commit: bool = True) -> Any:
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.is_staff = True
        user.is_superuser = True
        if commit:
            user.save()
        return user


class UserCreateForm(UserCreationForm):
    """Create an application user with an explicit billing role.

    Args:
        *args: Positional form arguments.
        **kwargs: Keyword form arguments.
    """

    username = forms.CharField(label="Benutzername")
    first_name = forms.CharField(label="Vorname", required=False)
    last_name = forms.CharField(label="Nachname", required=False)
    email = forms.EmailField(label="E-Mail-Adresse", required=True)
    phone = forms.CharField(label="Telefon", max_length=80, required=False)
    role = forms.ChoiceField(label="Rolle", choices=ROLE_CHOICES)
    password1 = forms.CharField(
        label="Passwort", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    password2 = forms.CharField(
        label="Passwort wiederholen", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    class Meta:
        model = get_user_model()
        fields = ["username", "first_name", "last_name", "email"]

    def save(self, commit: bool = True) -> Any:
        """Persist the user account without assigning groups.

        Args:
            commit: Whether to save the user immediately.

        Returns:
            The created user instance.
        """
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        user.is_active = True
        user.is_staff = self.cleaned_data["role"] == ROLE_ADMIN
        user.is_superuser = False
        if commit:
            user.save()
            UserProfile.objects.update_or_create(user=user, defaults={"phone": self.cleaned_data["phone"]})
        return user


class UserEditForm(forms.ModelForm):
    """Edit non-password user account metadata and billing role."""

    username = forms.CharField(label="Benutzername")
    first_name = forms.CharField(label="Vorname", required=False)
    last_name = forms.CharField(label="Nachname", required=False)
    email = forms.EmailField(label="E-Mail-Adresse", required=True)
    phone = forms.CharField(label="Telefon", max_length=80, required=False)
    is_active = forms.BooleanField(label="Aktiv", required=False)
    role = forms.ChoiceField(label="Rolle", choices=ROLE_CHOICES)

    class Meta:
        model = get_user_model()
        fields = ["username", "first_name", "last_name", "email", "is_active"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["role"].initial = user_role(self.instance)
        if self.instance.pk:
            try:
                self.fields["phone"].initial = self.instance.profile.phone
            except UserProfile.DoesNotExist:
                self.fields["phone"].initial = ""

    def clean_role(self) -> str:
        """Prevent misleading role changes for Django superusers."""
        role = self.cleaned_data["role"]
        if self.instance.is_superuser and role != ROLE_ADMIN:
            raise forms.ValidationError("Superuser bleiben immer Admins.", code="superuser_role")
        return role

    def save(self, commit: bool = True) -> Any:
        """Persist editable user metadata and the attached profile."""
        user = super().save(commit=commit)
        if commit:
            UserProfile.objects.update_or_create(user=user, defaults={"phone": self.cleaned_data["phone"]})
        return user


class UserPasswordResetForm(SetPasswordForm):
    """Set a new password for an existing user by an application admin."""

    new_password1 = forms.CharField(
        label="Neues Passwort", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    new_password2 = forms.CharField(
        label="Neues Passwort wiederholen",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )


class CampForm(forms.ModelForm):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize optional cutoff input with the project default."""
        super().__init__(*args, **kwargs)
        self.fields["meal_booking_cutoff_time"].required = False
        self.fields["meal_booking_cutoff_time"].initial = time(12, 0)

    class Meta:
        model = Camp
        fields = [
            "name",
            "year",
            "starts_on",
            "ends_on",
            "is_active",
            "meal_booking_cutoff_time",
            "shift_ratio_per_night",
            "iban",
            "paypal_link",
            "notes",
            "show_kiosk_invoices",
        ]
        labels = {
            "name": "Name",
            "year": "Jahr",
            "starts_on": "Beginn",
            "ends_on": "Ende",
            "is_active": "Aktiv",
            "meal_booking_cutoff_time": "Essens-Stichzeitpunkt",
            "shift_ratio_per_night": "Dienste pro gebuchter Nacht",
            "iban": "IBAN",
            "paypal_link": "PayPal.me Link",
            "notes": "Notizen",
            "show_kiosk_invoices": "Rechnungen im Kiosk anzeigen",
        }
        widgets = {
            "starts_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "ends_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "meal_booking_cutoff_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def clean_meal_booking_cutoff_time(self):
        """Return the default noon cutoff when the form field is omitted."""
        return self.cleaned_data["meal_booking_cutoff_time"] or time(12, 0)

    def clean_is_active(self):
        is_active = self.cleaned_data["is_active"]
        if self.instance.pk and self.instance.is_active and not is_active:
            raise forms.ValidationError("Aktiviere stattdessen ein anderes Lager.")
        return is_active


class MealPreorderSettingsForm(forms.ModelForm):
    class Meta:
        model = Camp
        fields = ["allow_breakfast_prebooking_before_camp", "allow_dinner_prebooking_before_camp"]
        labels = {
            "allow_breakfast_prebooking_before_camp": "Frühstück vor Lagerbeginn freigeben",
            "allow_dinner_prebooking_before_camp": "Abendessen vor Lagerbeginn freigeben",
        }


class MealCutoffForm(forms.ModelForm):
    """Edit the camp meal booking cutoff without exposing other camp settings."""

    class Meta:
        model = Camp
        fields = ["meal_booking_cutoff_time"]
        labels = {"meal_booking_cutoff_time": "Essens-Stichzeitpunkt"}
        widgets = {"meal_booking_cutoff_time": forms.TimeInput(attrs={"type": "time"})}

    def clean_meal_booking_cutoff_time(self):
        """Return the default noon cutoff when the form field is omitted."""
        return self.cleaned_data["meal_booking_cutoff_time"] or time(12, 0)


class ParticipantForm(forms.ModelForm):
    class Meta:
        model = Participant
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "status",
            "is_child",
            "is_youth_group",
            "is_companion",
            "hilfssatz",
            "berufssatz",
            "arrival_date",
            "departure_date",
            "booked_nights",
            "actual_nights",
            "notes",
        ]
        labels = {
            "first_name": "Vorname",
            "last_name": "Nachname",
            "email": "E-Mail-Adresse",
            "phone": "Telefon",
            "status": "Status",
            "is_child": "Kind",
            "is_youth_group": "Jugendgruppe",
            "is_companion": "Begleitperson",
            "hilfssatz": "Hilfssatz",
            "berufssatz": "Berufssatz",
            "arrival_date": "Anreise",
            "departure_date": "Abreise",
            "booked_nights": "Gebuchte Nächte",
            "actual_nights": "Tatsächliche Nächte",
            "notes": "Notizen",
        }
        widgets = {
            "hilfssatz": forms.NumberInput(attrs={"step": "0.0001", "min": "0", "max": "1"}),
            "berufssatz": forms.NumberInput(attrs={"step": "0.0001", "min": "0", "max": "1"}),
            "arrival_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "departure_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def clean(self) -> dict[str, Any]:
        """Validate that the departure date is after the arrival date."""
        cleaned_data = super().clean() or {}
        arrival_date = cleaned_data.get("arrival_date")
        departure_date = cleaned_data.get("departure_date")
        if arrival_date and departure_date and departure_date <= arrival_date:
            self.add_error("departure_date", "Die Abreise muss nach der Anreise liegen.")
        return cleaned_data


class PriceRuleForm(forms.ModelForm):
    foerdersatz = SubsidyPercentField()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if not self.is_bound and self.instance.pk:
            self.initial["foerdersatz"] = subsidy_percentage(self.instance.foerdersatz)

    class Meta:
        model = PriceRule
        fields = [
            "kind",
            "name",
            "unit_price",
            "camp_flat_duration",
            "camp_flat_role",
            "applies_to_children",
            "applies_to_adults",
            "applies_to_companions",
            "foerdersatz",
            "is_default",
            "meal_type",
            "meal_date",
        ]
        labels = {
            "kind": "Art",
            "name": "Name",
            "unit_price": "Einzelpreis",
            "camp_flat_duration": "Lagerpauschale für",
            "camp_flat_role": "Personengruppe",
            "applies_to_children": "Gilt für Kinder",
            "applies_to_adults": "Gilt für Erwachsene",
            "applies_to_companions": "Gilt für Begleitpersonen",
            "foerdersatz": "Fördersatz (%)",
            "is_default": "Standardregel",
            "meal_type": "Mahlzeit",
            "meal_date": "Datum",
        }
        widgets = {
            "kind": forms.RadioSelect,
            "camp_flat_duration": forms.RadioSelect,
            "camp_flat_role": forms.RadioSelect,
        }

    def clean(self):
        cleaned_data = super().clean()
        kind = cleaned_data.get("kind")
        if kind == PriceRule.Kind.CAMP_FLAT:
            if not cleaned_data.get("camp_flat_duration"):
                self.add_error("camp_flat_duration", "Bitte 1 Woche oder 2 Wochen auswählen.")
            if not cleaned_data.get("camp_flat_role"):
                self.add_error("camp_flat_role", "Bitte Teilnehmer oder Begleitperson auswählen.")
        else:
            cleaned_data["camp_flat_duration"] = ""
            cleaned_data["camp_flat_role"] = ""
        return cleaned_data


class CampFlatRateSettingsForm(forms.Form):
    participant_1w_price = forms.DecimalField(label="Teilnehmer 1 Woche", min_value=0, max_digits=10, decimal_places=2)
    participant_1w_foerdersatz = SubsidyPercentField()
    participant_2w_price = forms.DecimalField(label="Teilnehmer 2 Wochen", min_value=0, max_digits=10, decimal_places=2)
    participant_2w_foerdersatz = SubsidyPercentField()
    companion_1w_price = forms.DecimalField(label="Begleitperson 1 Woche", min_value=0, max_digits=10, decimal_places=2)
    companion_1w_foerdersatz = SubsidyPercentField()
    companion_2w_price = forms.DecimalField(
        label="Begleitperson 2 Wochen",
        min_value=0,
        max_digits=10,
        decimal_places=2,
    )
    companion_2w_foerdersatz = SubsidyPercentField()

    variants = [
        (
            "participant_1w",
            "Teilnehmer",
            PriceRule.CampFlatRole.PARTICIPANT,
            "1 Woche",
            PriceRule.CampFlatDuration.ONE_WEEK,
        ),
        (
            "participant_2w",
            "Teilnehmer",
            PriceRule.CampFlatRole.PARTICIPANT,
            "2 Wochen",
            PriceRule.CampFlatDuration.TWO_WEEKS,
        ),
        (
            "companion_1w",
            "Begleitperson",
            PriceRule.CampFlatRole.COMPANION,
            "1 Woche",
            PriceRule.CampFlatDuration.ONE_WEEK,
        ),
        (
            "companion_2w",
            "Begleitperson",
            PriceRule.CampFlatRole.COMPANION,
            "2 Wochen",
            PriceRule.CampFlatDuration.TWO_WEEKS,
        ),
    ]

    def __init__(self, *args, camp=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.camp = camp
        if camp is None or self.is_bound:
            return
        rules = {
            (rule.camp_flat_role, rule.camp_flat_duration): rule
            for rule in PriceRule.objects.filter(camp=camp, kind=PriceRule.Kind.CAMP_FLAT)
        }
        for prefix, _role_label, role, _duration_label, duration in self.variants:
            rule = rules.get((role, duration))
            if rule is not None:
                self.fields[f"{prefix}_price"].initial = rule.unit_price
                self.fields[f"{prefix}_foerdersatz"].initial = subsidy_percentage(rule.foerdersatz)
            else:
                self.fields[f"{prefix}_price"].initial = 0
                self.fields[f"{prefix}_foerdersatz"].initial = Decimal("0")

    def rows(self):
        return [
            {
                "role": role_label,
                "duration": duration_label,
                "price": self[f"{prefix}_price"],
                "foerdersatz": self[f"{prefix}_foerdersatz"],
            }
            for prefix, role_label, _role, duration_label, _duration in self.variants
        ]

    def save(self):
        if self.camp is None:
            raise ValueError("CampFlatRateSettingsForm.save() requires camp.")
        with transaction.atomic():
            for prefix, role_label, role, duration_label, duration in self.variants:
                rule = (
                    PriceRule.objects.filter(
                        camp=self.camp,
                        kind=PriceRule.Kind.CAMP_FLAT,
                        camp_flat_role=role,
                        camp_flat_duration=duration,
                    )
                    .order_by("pk")
                    .first()
                )
                if rule is None:
                    rule = PriceRule(
                        camp=self.camp,
                        kind=PriceRule.Kind.CAMP_FLAT,
                        camp_flat_role=role,
                        camp_flat_duration=duration,
                    )
                rule.name = f"Lagerpauschale {role_label} {duration_label}"
                rule.unit_price = self.cleaned_data[f"{prefix}_price"]
                rule.applies_to_children = True
                rule.applies_to_adults = True
                rule.applies_to_companions = True
                rule.foerdersatz = self.cleaned_data[f"{prefix}_foerdersatz"]
                rule.is_default = True
                rule.save()
                PriceRule.objects.filter(
                    camp=self.camp,
                    kind=PriceRule.Kind.CAMP_FLAT,
                    camp_flat_role=role,
                    camp_flat_duration=duration,
                ).exclude(pk=rule.pk).update(is_default=False)


class ChargeForm(forms.ModelForm):
    foerdersatz = SubsidyPercentField()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if not self.is_bound and self.instance.pk:
            self.initial["foerdersatz"] = subsidy_percentage(self.instance.foerdersatz)

    class Meta:
        model = Charge
        fields = ["kind", "description", "quantity", "unit_price", "foerdersatz", "occurred_on"]
        labels = {
            "kind": "Art",
            "description": "Beschreibung",
            "quantity": "Menge",
            "unit_price": "Einzelpreis",
            "foerdersatz": "Fördersatz (%)",
            "occurred_on": "Datum",
        }
        widgets = {"occurred_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}


class _ManualPriceRuleChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: PriceRule) -> str:
        localized_price = number_format(obj.unit_price, decimal_pos=2, use_l10n=True, force_grouping=True)
        return f"{obj.name} ({localized_price} €)"


class ManualChargeForm(forms.Form):
    """Validate a price-rule-backed manual charge for one camp."""

    price_rule_id = _ManualPriceRuleChoiceField(
        label="Preisregel auswählen",
        queryset=PriceRule.objects.none(),
        empty_label=None,
    )
    quantity = forms.IntegerField(
        label="Menge",
        min_value=1,
        max_value=99,
        initial=1,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": "1", "max": "99", "step": "1"}),
    )
    description = forms.CharField(
        label="Notiz (optional)",
        required=False,
        max_length=180,
        widget=forms.TextInput(attrs={"placeholder": "Zusätzliche Info für die Abrechnung"}),
    )

    def __init__(self, *args: Any, camp: Camp, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        price_rules = PriceRule.objects.filter(camp=camp, is_archived=False).order_by("name")
        price_rule_field = cast(_ManualPriceRuleChoiceField, self.fields["price_rule_id"])
        price_rule_field.queryset = price_rules

    def add_error(self, field: str | None, error: Any) -> None:
        """Attach field errors to their widgets for accessible rendering."""
        super().add_error(field, error)
        if field is None or field not in self.fields:
            return
        self.fields[field].widget.attrs.update(
            {
                "aria-describedby": f"id_{field}_error",
                "aria-invalid": "true",
            }
        )


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["amount", "paid_on", "method", "note"]
        labels = {
            "amount": "Betrag",
            "paid_on": "Zahlungsdatum",
            "method": "Zahlungsart",
            "note": "Notiz",
        }
        widgets = {"paid_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}


EXPENSE_CATEGORY_CHOICES = [
    ("Unterkunft/Verpflegung", "Unterkunft/Verpflegung"),
    ("Fahrtkosten", "Fahrtkosten"),
    ("Verbrauchsmaterial", "Verbrauchsmaterial"),
    ("Miete/sonstiges", "Miete/sonstiges"),
]


class ExpenseAdminForm(forms.ModelForm):
    """Apply receipt boundary validation to Django's administrative expense form."""

    def clean_receipt(self) -> Any:
        receipt = self.cleaned_data.get("receipt")
        return validate_receipt_upload(receipt) if isinstance(receipt, UploadedFile) else receipt

    class Meta:
        model = Expense
        fields = [
            "camp",
            "participant",
            "category",
            "description",
            "amount",
            "receipt",
            "paid_on",
            "reimbursable",
            "status",
            "rejection_reason",
            "allocation_method",
            "cost_center",
            "approved_at",
            "approved_by",
        ]


class ExpenseForm(forms.ModelForm):
    def clean_receipt(self) -> Any:
        """Validate the optional receipt upload attached to an administrative expense."""
        receipt = self.cleaned_data.get("receipt")
        return validate_receipt_upload(receipt) if isinstance(receipt, UploadedFile) else receipt

    class Meta:
        model = Expense
        fields = ["participant", "category", "description", "amount", "receipt", "paid_on", "reimbursable"]
        labels = {
            "participant": "Teilnehmer",
            "category": "Kategorie",
            "description": "Beschreibung",
            "amount": "Betrag",
            "receipt": "Rechnungsbeleg",
            "paid_on": "Zahlungsdatum",
            "reimbursable": "Erstattungsfähig",
        }
        widgets = {
            "paid_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "category": forms.Select(choices=EXPENSE_CATEGORY_CHOICES),
            "receipt": forms.FileInput(
                attrs={
                    "accept": "application/pdf,image/jpeg,image/png,image/heic,.pdf,.jpg,.jpeg,.png,.heic",
                    "capture": "environment",
                }
            ),
        }


class SharedExpenseRequestForm(forms.ModelForm):
    def clean_receipt(self) -> Any:
        """Validate the optional receipt upload attached to a kiosk expense request."""
        receipt = self.cleaned_data.get("receipt")
        return validate_receipt_upload(receipt) if isinstance(receipt, UploadedFile) else receipt

    class Meta:
        model = Expense
        fields = ["category", "description", "amount", "receipt", "paid_on"]
        labels = {
            "category": "Kategorie",
            "description": "Beschreibung",
            "amount": "Betrag",
            "receipt": "Rechnungsbeleg",
            "paid_on": "Zahlungsdatum",
        }
        widgets = {
            "paid_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "category": forms.Select(choices=EXPENSE_CATEGORY_CHOICES),
            "receipt": forms.FileInput(
                attrs={
                    "accept": "application/pdf,image/jpeg,image/png,image/heic,.pdf,.jpg,.jpeg,.png,.heic",
                    "capture": "environment",
                }
            ),
        }


class SharedExpenseApprovalForm(forms.ModelForm):
    participant_ids = forms.MultipleChoiceField(
        label="Umlage auf",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Expense
        fields = ["allocation_method", "cost_center"]
        labels = {
            "allocation_method": "Umlagemethode",
            "cost_center": "Kostenstelle",
        }

    def __init__(self, *args, camp=None, **kwargs):
        super().__init__(*args, **kwargs)
        if camp:
            participants = Participant.objects.filter(camp=camp, archived_at__isnull=True).order_by(
                "last_name", "first_name"
            )
            self.fields["participant_ids"].choices = [(p.id, p.full_name) for p in participants]
        # Only require cost center if the allocation method is COST_CENTER
        self.fields["cost_center"].required = False

    def clean(self):
        cleaned_data = super().clean()
        allocation_method = cleaned_data.get("allocation_method")
        participant_ids = cleaned_data.get("participant_ids")
        cost_center = cleaned_data.get("cost_center")

        if allocation_method == Expense.AllocationMethod.SELECTED and not participant_ids:
            self.add_error("participant_ids", "Bitte wähle mindestens einen Teilnehmer aus.")

        if allocation_method == Expense.AllocationMethod.COST_CENTER and not cost_center:
            self.add_error("cost_center", "Bitte wähle eine Kostenstelle aus.")

        return cleaned_data


class ParticipantImportForm(forms.Form):
    file = forms.FileField(
        label="Importdatei",
        help_text="CSV oder XLSX mit den Spalten first_name, last_name, hilfssatz und berufssatz",
        validators=[FileExtensionValidator(allowed_extensions=["csv", "xlsx"])],
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > MAX_IMPORT_FILE_SIZE:
            raise forms.ValidationError("Die Importdatei darf höchstens 5 MB groß sein.", code="file_too_large")
        return upload


class ParticipantPinForm(forms.Form):
    pin = forms.CharField(
        label="Neue PIN",
        min_length=4,
        max_length=10,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
    )


class KioskCampAccessForm(forms.Form):
    """Collect the shared PIN required before any participant kiosk flow."""

    pin = forms.CharField(
        label="Lager-PIN",
        strip=True,
        validators=[validate_kiosk_camp_pin],
        widget=forms.PasswordInput(
            attrs={"autocomplete": "current-password", "inputmode": "numeric", "minlength": "6", "maxlength": "12"}
        ),
    )


class CampKioskAccessAdminForm(forms.Form):
    """Validate a new shared kiosk PIN entered by an administrator."""

    pin = forms.CharField(
        label="Neue Lager-PIN",
        strip=True,
        validators=[validate_kiosk_camp_pin],
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password", "inputmode": "numeric", "minlength": "6", "maxlength": "12"}
        ),
    )
    pin_repeat = forms.CharField(
        label="Lager-PIN wiederholen",
        strip=True,
        validators=[validate_kiosk_camp_pin],
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password", "inputmode": "numeric", "minlength": "6", "maxlength": "12"}
        ),
    )

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        pin = cleaned_data.get("pin")
        pin_repeat = cleaned_data.get("pin_repeat")
        if pin and pin_repeat and pin != pin_repeat:
            self.add_error("pin_repeat", "Die Lager-PINs stimmen nicht überein.")
        return cleaned_data


class KioskLoginForm(forms.Form):
    participant = forms.ChoiceField(label="Teilnehmer")
    pin = forms.CharField(
        label="PIN",
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "inputmode": "numeric"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.login_targets = self._login_targets()
        self.fields["participant"].choices = [
            ("", "Bitte Teilnehmer auswählen"),
            *((target["token"], target["label"]) for target in self.login_targets),
        ]

    def _login_targets(self) -> list[dict[str, Any]]:
        participants = (
            Participant.objects.filter(camp__is_active=True, archived_at__isnull=True)
            .exclude(status=Participant.Status.PENDING_APPROVAL)
            .select_related("camp")
        )
        targets = [
            {
                "token": f"participant-{participant.pk}",
                "label": participant.full_name,
                "participant": participant,
                "family_member": None,
            }
            for participant in participants
        ]
        family_members = (
            ParticipantFamilyMember.objects.select_related("guardian", "guardian__camp")
            .filter(
                guardian__camp__is_active=True,
                guardian__archived_at__isnull=True,
                role=ParticipantFamilyMember.Role.COMPANION,
                is_active=True,
            )
            .order_by("last_name", "first_name", "pk")
        )
        targets.extend(
            {
                "token": f"family-{family_member.pk}",
                "label": f"{family_member.full_name} (Begleitung von {family_member.guardian.full_name})",
                "participant": family_member.guardian,
                "family_member": family_member,
            }
            for family_member in family_members
        )

        def name_sort_key(target: dict[str, Any]) -> tuple[str, str, str]:
            person = target["family_member"] or target["participant"]
            return (person.last_name.casefold(), person.first_name.casefold(), target["token"])

        return sorted(targets, key=name_sort_key)

    def _target_for_token(self, token: str) -> dict[str, Any] | None:
        return next((target for target in self.login_targets if target["token"] == token), None)

    def clean(self):
        cleaned_data = super().clean()
        target = self._target_for_token(cleaned_data.get("participant", ""))
        pin = cleaned_data.get("pin")
        if target:
            participant = target["participant"]
            family_member = target["family_member"]
            if family_member is not None:
                try:
                    family_pin = family_member.pin
                except ParticipantFamilyMemberPin.DoesNotExist:
                    family_pin = None
                if family_pin is None or family_pin.must_set_pin or not family_pin.pin_hash:
                    raise forms.ValidationError(
                        "Die PIN muss zuerst durch den zugehörigen Teilnehmer gesetzt werden.",
                        code="missing_pin",
                    )
                if family_pin.is_locked:
                    raise forms.ValidationError(
                        "Zu viele Fehlversuche. Bitte warte fünf Minuten und versuche es erneut.", code="pin_locked"
                    )
                if pin and not family_pin.check_pin(pin):
                    raise forms.ValidationError("Teilnehmer oder PIN ist ungültig.", code="invalid_pin")
                cleaned_data["participant"] = participant
                cleaned_data["family_member"] = family_member
                return cleaned_data
            try:
                participant_pin = participant.pin
            except ParticipantPin.DoesNotExist:
                participant_pin = None
            if participant_pin is None or participant_pin.must_set_pin or not participant_pin.pin_hash:
                raise forms.ValidationError(
                    "Die PIN muss zuerst von der Lagerleitung gesetzt werden.",
                    code="missing_pin",
                )
            if participant_pin.is_locked:
                raise forms.ValidationError(
                    "Zu viele Fehlversuche. Bitte warte fünf Minuten und versuche es erneut.", code="pin_locked"
                )
            if pin and not participant_pin.check_pin(pin):
                raise forms.ValidationError("Teilnehmer oder PIN ist ungültig.", code="invalid_pin")
            cleaned_data["participant"] = participant
            cleaned_data["family_member"] = None
        return cleaned_data


class KioskFamilyMemberPinForm(forms.Form):
    """Set a raw PIN for an existing companion owned by the kiosk participant."""

    pin = forms.CharField(
        label="Neuer PIN",
        min_length=4,
        max_length=10,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
    )
    pin_repeat = forms.CharField(
        label="PIN wiederholen",
        min_length=4,
        max_length=10,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        pin = cleaned_data.get("pin")
        pin_repeat = cleaned_data.get("pin_repeat")
        if pin and pin_repeat and pin != pin_repeat:
            raise forms.ValidationError("Die PINs stimmen nicht überein.", code="pin_mismatch")
        return cleaned_data


class KioskPinChangeForm(forms.Form):
    """Validate a personal PIN change for the authenticated kiosk actor."""

    current_pin = forms.CharField(
        label="Aktuelle PIN",
        min_length=4,
        max_length=10,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "inputmode": "numeric"}),
    )
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

    def __init__(self, *args: Any, pin_record: ParticipantPin | ParticipantFamilyMemberPin, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pin_record = pin_record

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        current_pin = cleaned_data.get("current_pin")
        pin = cleaned_data.get("pin")
        pin_repeat = cleaned_data.get("pin_repeat")

        current_pin_is_valid = False
        if current_pin:
            if self.pin_record.is_locked:
                self.add_error(
                    "current_pin",
                    "Zu viele Fehlversuche. Bitte warte fünf Minuten und versuche es erneut.",
                )
            elif not self.pin_record.check_pin(current_pin):
                self.add_error("current_pin", "Die aktuelle PIN ist nicht korrekt.")
            else:
                current_pin_is_valid = True

        if pin and pin_repeat and pin != pin_repeat:
            self.add_error("pin_repeat", "Die PINs stimmen nicht überein.")
        if pin and _is_trivial_personal_pin(pin):
            self.add_error(
                "pin",
                "Bitte wähle eine sicherere PIN (keine einfachen Zahlenfolgen wie '1234' oder '0000').",
            )
        if current_pin_is_valid and pin and pin == current_pin:
            self.add_error("pin", "Die neue PIN muss sich von der aktuellen PIN unterscheiden.")
        return cleaned_data


class KioskSelfEnrollmentForm(forms.ModelForm):
    pin = forms.CharField(
        label="Persönliche PIN",
        min_length=4,
        max_length=12,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
    )
    pin_repeat = forms.CharField(
        label="PIN wiederholen",
        min_length=4,
        max_length=12,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
    )

    def __init__(self, *args: Any, camp: Camp | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.camp = camp
        if camp:
            if camp.starts_on:
                earliest = camp.starts_on - timedelta(days=4)
                self.fields["arrival_date"].widget.attrs["min"] = earliest.isoformat()
                self.fields["departure_date"].widget.attrs["min"] = earliest.isoformat()
            if camp.ends_on:
                latest = camp.ends_on + timedelta(days=4)
                self.fields["arrival_date"].widget.attrs["max"] = latest.isoformat()
                self.fields["departure_date"].widget.attrs["max"] = latest.isoformat()

    class Meta:
        model = Participant
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "arrival_date",
            "departure_date",
            "is_child",
            "is_youth_group",
            "is_companion",
            "notes",
        ]
        labels = {
            "first_name": "Vorname",
            "last_name": "Nachname",
            "email": "E-Mail (optional)",
            "phone": "Telefonnummer (optional)",
            "arrival_date": "Anreisedatum (optional)",
            "departure_date": "Abreisedatum (optional)",
            "is_child": "Kind (ermäßigt)",
            "is_youth_group": "Jugendgruppe",
            "is_companion": "Begleitperson",
            "notes": "Anmerkung (optional)",
        }
        widgets = {
            "arrival_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "departure_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def clean(self) -> dict[str, Any]:
        """Validate matching PIN values and camp arrival/departure date bounds."""
        cleaned_data = super().clean() or {}
        pin = cleaned_data.get("pin")
        pin_repeat = cleaned_data.get("pin_repeat")
        if pin and pin_repeat and pin != pin_repeat:
            self.add_error("pin_repeat", "Die PINs stimmen nicht überein.")

        if pin and _is_trivial_personal_pin(pin):
            self.add_error(
                "pin",
                "Bitte wähle eine sicherere PIN (keine einfachen Zahlenfolgen wie '1234' oder '0000').",
            )

        arrival_date = cleaned_data.get("arrival_date")
        departure_date = cleaned_data.get("departure_date")

        if arrival_date and departure_date and departure_date <= arrival_date:
            self.add_error("departure_date", "Die Abreise muss nach der Anreise liegen.")

        if self.camp:
            if self.camp.starts_on:
                earliest = self.camp.starts_on - timedelta(days=4)
                starts_formatted = self.camp.starts_on.strftime("%d.%m.%Y")
                if arrival_date and arrival_date < earliest:
                    self.add_error(
                        "arrival_date",
                        (
                            "Das Anreisedatum darf maximal 4 Tage (halbe Woche) "
                            f"vor Lagerbeginn ({starts_formatted}) liegen."
                        ),
                    )
                if departure_date and departure_date < earliest:
                    self.add_error(
                        "departure_date",
                        (
                            "Das Abreisedatum darf maximal 4 Tage (halbe Woche) "
                            f"vor Lagerbeginn ({starts_formatted}) liegen."
                        ),
                    )
            if self.camp.ends_on:
                latest = self.camp.ends_on + timedelta(days=4)
                ends_formatted = self.camp.ends_on.strftime("%d.%m.%Y")
                if arrival_date and arrival_date > latest:
                    self.add_error(
                        "arrival_date",
                        (
                            "Das Anreisedatum darf maximal 4 Tage (halbe Woche) "
                            f"nach Lagerende ({ends_formatted}) liegen."
                        ),
                    )
                if departure_date and departure_date > latest:
                    self.add_error(
                        "departure_date",
                        (
                            "Das Abreisedatum darf maximal 4 Tage (halbe Woche) "
                            f"nach Lagerende ({ends_formatted}) liegen."
                        ),
                    )

        return cleaned_data


class ParticipantRegistrationApprovalForm(forms.ModelForm):
    """Require an explicit administrative decision on price-relevant attributes."""

    RATE_FIELDS = ("hilfssatz", "berufssatz")

    price_attributes_confirmed = forms.BooleanField(
        label="Preisrelevante Angaben geprüft",
        help_text="Kind, Jugendgruppe und Begleitperson wurden vor der Freigabe kontrolliert.",
        required=True,
    )

    class Meta:
        model = Participant
        fields = ["is_child", "is_youth_group", "is_companion", "hilfssatz", "berufssatz"]
        labels = {
            "is_child": "Kind",
            "is_youth_group": "Jugendgruppe",
            "is_companion": "Begleitperson",
            "hilfssatz": "Hilfssatz",
            "berufssatz": "Berufssatz",
        }
        widgets = {
            "hilfssatz": forms.NumberInput(attrs={"step": "0.0001", "min": "0", "max": "1"}),
            "berufssatz": forms.NumberInput(attrs={"step": "0.0001", "min": "0", "max": "1"}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for field_name in self.RATE_FIELDS:
            self.fields[field_name].required = False

    def clean(self) -> dict[str, Any]:
        """Require both subsidy factors only for youth-group participants."""
        cleaned_data = super().clean() or {}
        if cleaned_data.get("is_youth_group"):
            rate_labels = {
                "hilfssatz": "Hilfssatz",
                "berufssatz": "Berufssatz",
            }
            for field_name in self.RATE_FIELDS:
                if cleaned_data.get(field_name) is None:
                    self.add_error(
                        field_name,
                        f"Bitte gib den {rate_labels[field_name]} für die Jugendgruppe ein.",
                    )
            return cleaned_data

        for field_name in self.RATE_FIELDS:
            if cleaned_data.get(field_name) is None:
                cleaned_data[field_name] = getattr(self.instance, field_name)
        return cleaned_data


class QuickBookingForm(forms.Form):
    price_rule = forms.ModelChoiceField(label="Artikel", queryset=PriceRule.objects.none())
    quantity = forms.IntegerField(
        label="Menge",
        min_value=1,
        max_value=99,
        initial=1,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": "1", "max": "99", "step": "1"}),
    )

    def __init__(self, *args, **kwargs):
        camp = kwargs.pop("camp", None)
        participant = kwargs.pop("participant", None)
        target_groups = kwargs.pop("target_groups", None)
        super().__init__(*args, **kwargs)
        if participant is not None:
            camp = participant.camp
        if camp is not None:
            from django.db.models import Q

            queryset = PriceRule.objects.filter(
                Q(kind=PriceRule.Kind.DRINK)
                | Q(kind=PriceRule.Kind.MEAL, meal_type__in=[PriceRule.MealType.BREAKFAST, PriceRule.MealType.SNACK]),
                camp=camp,
                is_archived=False,
                meal_date__isnull=True,
            ).order_by("name")
            if target_groups is not None:
                applicability = Q(pk__in=[])
                if "child" in target_groups:
                    applicability |= Q(applies_to_children=True)
                if "adult" in target_groups:
                    applicability |= Q(applies_to_adults=True)
                if "companion" in target_groups:
                    applicability |= Q(applies_to_companions=True)
                queryset = queryset.filter(applicability)
            elif participant is not None:
                if participant.is_child:
                    queryset = queryset.filter(applies_to_children=True)
                elif participant.is_companion:
                    queryset = queryset.filter(applies_to_companions=True)
                else:
                    queryset = queryset.filter(applies_to_adults=True)
            self.fields["price_rule"].queryset = queryset
        self.fields["price_rule"].label_from_instance = lambda rule: f"{rule.name} - {rule.unit_price} EUR"


class KioskFamilyMemberForm(forms.ModelForm):
    """Create a kiosk-only family member for bundled participant billing."""

    pin = forms.CharField(
        label="Persönliche PIN für Begleitperson",
        min_length=4,
        max_length=12,
        strip=True,
        required=False,
        help_text="Nur für Begleitpersonen mit eigenem Kiosk-Login erforderlich.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
    )
    pin_repeat = forms.CharField(
        label="PIN wiederholen",
        min_length=4,
        max_length=12,
        strip=True,
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
    )

    class Meta:
        model = ParticipantFamilyMember
        fields = ["first_name", "last_name", "role"]
        labels = {
            "first_name": "Vorname",
            "last_name": "Nachname",
            "role": "Rolle",
        }

    def clean(self) -> dict[str, Any]:
        """Require a confirmed PIN when the family member receives a login."""
        cleaned_data = super().clean() or {}
        if cleaned_data.get("role") != ParticipantFamilyMember.Role.COMPANION:
            return cleaned_data

        pin = cleaned_data.get("pin")
        pin_repeat = cleaned_data.get("pin_repeat")
        if not pin:
            self.add_error("pin", "Begleitpersonen benötigen eine PIN.")
        if not pin_repeat:
            self.add_error("pin_repeat", "Bitte wiederhole die PIN.")
        if pin and pin_repeat and pin != pin_repeat:
            self.add_error("pin_repeat", "Die PINs stimmen nicht überein.")
        return cleaned_data


class KioskBookingLinkInviteForm(forms.Form):
    """Invite another active camp participant to a reciprocal current-camp authorization."""

    participant = forms.ModelChoiceField(label="Teilnehmer einladen", queryset=Participant.objects.none())

    def __init__(self, *args, **kwargs):
        self.inviter = kwargs.pop("inviter")
        super().__init__(*args, **kwargs)
        active_statuses = [
            ParticipantBookingLink.Status.PENDING,
            ParticipantBookingLink.Status.ACCEPTED,
        ]
        linked_participant_ids = {
            invitee_id if inviter_id == self.inviter.pk else inviter_id
            for inviter_id, invitee_id in ParticipantBookingLink.objects.filter(
                models.Q(inviter=self.inviter) | models.Q(invitee=self.inviter),
                status__in=active_statuses,
            ).values_list("inviter_id", "invitee_id")
        }
        self.fields["participant"].queryset = (
            Participant.objects.filter(camp=self.inviter.camp, camp__is_active=True, archived_at__isnull=True)
            .exclude(pk__in={self.inviter.pk, *linked_participant_ids})
            .order_by("last_name", "first_name")
        )

    def clean_participant(self):
        """Reject duplicate active invitations for the same participant pair."""
        participant = self.cleaned_data["participant"]
        active_statuses = [
            ParticipantBookingLink.Status.PENDING,
            ParticipantBookingLink.Status.ACCEPTED,
        ]
        existing_link = ParticipantBookingLink.objects.filter(
            models.Q(inviter=self.inviter, invitee=participant) | models.Q(inviter=participant, invitee=self.inviter),
            status__in=active_statuses,
        ).exists()
        if existing_link:
            raise forms.ValidationError("Zwischen diesen Teilnehmern besteht bereits eine offene Verknüpfung.")
        return participant


class MealPlanForm(forms.Form):
    """Edit dinner menu descriptions for the visible camp meal calendar."""

    def __init__(self, *args: Any, camp: Camp, meal_dates: list[date], **kwargs: Any) -> None:
        self.camp = camp
        self.meal_dates = meal_dates
        super().__init__(*args, **kwargs)
        existing_entries = {
            entry.meal_date: entry.description
            for entry in MealPlanEntry.objects.filter(camp=camp, meal=MealSignup.Meal.DINNER)
        }
        for meal_date in meal_dates:
            field_name = self.field_name(meal_date)
            self.fields[field_name] = forms.CharField(
                label=f"Speiseplan {meal_date:%d.%m.%Y}",
                required=False,
                max_length=500,
                initial=existing_entries.get(meal_date, ""),
                widget=forms.Textarea(attrs={"rows": 2, "maxlength": "500"}),
            )

    @staticmethod
    def field_name(meal_date: date) -> str:
        """Return the stable dynamic field name for a meal date."""
        return f"description_{meal_date:%Y%m%d}"

    def save(self) -> None:
        """Persist non-empty descriptions and remove cleared menu entries."""
        with transaction.atomic():
            for meal_date in self.meal_dates:
                description = self.cleaned_data.get(self.field_name(meal_date), "").strip()
                if description:
                    MealPlanEntry.objects.update_or_create(
                        camp=self.camp,
                        meal_date=meal_date,
                        meal=MealSignup.Meal.DINNER,
                        defaults={"description": description},
                    )
                else:
                    MealPlanEntry.objects.filter(
                        camp=self.camp,
                        meal_date=meal_date,
                        meal=MealSignup.Meal.DINNER,
                    ).delete()


class MealBookingForm(forms.Form):
    meal_dates = forms.TypedMultipleChoiceField(
        label="Lagertage",
        choices=(),
        coerce=date.fromisoformat,
        empty_value=[],
        error_messages={"required": "Bitte mindestens einen Lagertag auswählen."},
    )
    meal = forms.ChoiceField(label="Mahlzeit", choices=MealSignup.Meal.choices)
    variant = forms.ChoiceField(label="Variante", choices=MealSignup.Variant.choices)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Limit selectable dates to the participant's configured camp days."""
        participant = kwargs.pop("participant", None)
        kwargs.pop("camp", None)
        super().__init__(*args, **kwargs)
        self.participant = participant
        if participant is not None:
            from .services import camp_meal_dates

            meal_dates_field = cast(forms.TypedMultipleChoiceField, self.fields["meal_dates"])
            variant_field = cast(forms.ChoiceField, self.fields["variant"])
            camp = participant.camp
            has_valid_camp_bounds = (
                camp.starts_on is not None and camp.ends_on is not None and camp.starts_on <= camp.ends_on
            )
            selectable_dates = camp_meal_dates(camp) if has_valid_camp_bounds else []
            meal_dates_field.choices = [
                (meal_date.isoformat(), meal_date.strftime("%d.%m.%Y")) for meal_date in sorted(set(selectable_dates))
            ]
            if participant.is_child:
                variant_field.choices = [
                    (MealSignup.Variant.NORMAL_CHILD, "Mit Fleisch (Kind)"),
                    (MealSignup.Variant.VEGAN_CHILD, "Vegan/Vegetarisch (Kind)"),
                ]
            else:
                variant_field.choices = [
                    (MealSignup.Variant.NORMAL, "Mit Fleisch"),
                    (MealSignup.Variant.VEGAN, "Vegan/Vegetarisch"),
                ]

    def clean_meal_dates(self) -> list[date]:
        """Return unique selected camp dates in chronological order within camp bounds."""
        selected_dates = sorted(set(self.cleaned_data["meal_dates"]))
        if getattr(self, "participant", None) and self.participant.camp:
            camp = self.participant.camp
            if camp.starts_on is None or camp.ends_on is None or camp.starts_on > camp.ends_on:
                raise forms.ValidationError("Der Lagerzeitraum ist nicht gültig konfiguriert.")
            invalid_dates = [d for d in selected_dates if d < camp.starts_on or d > camp.ends_on]
            if invalid_dates:
                raise forms.ValidationError("Ausgewählte Daten liegen außerhalb des Lagerzeitraums.")
        return selected_dates


class MealStandardPricesForm(forms.Form):
    breakfast_adult_price = forms.DecimalField(
        label="Frühstück Erwachsene", max_digits=6, decimal_places=2, min_value=0, required=False
    )
    breakfast_adult_foerdersatz = SubsidyPercentField()
    breakfast_child_price = forms.DecimalField(
        label="Frühstück Kinder", max_digits=6, decimal_places=2, min_value=0, required=False
    )
    breakfast_child_foerdersatz = SubsidyPercentField()

    dinner_adult_price = forms.DecimalField(
        label="Abendessen Erwachsene", max_digits=6, decimal_places=2, min_value=0, required=False
    )
    dinner_adult_foerdersatz = SubsidyPercentField()
    dinner_child_price = forms.DecimalField(
        label="Abendessen Kinder", max_digits=6, decimal_places=2, min_value=0, required=False
    )
    dinner_child_foerdersatz = SubsidyPercentField()

    snack_adult_price = forms.DecimalField(
        label="Mittagssnack Erwachsene", max_digits=6, decimal_places=2, min_value=0, required=False
    )
    snack_adult_foerdersatz = SubsidyPercentField()
    snack_child_price = forms.DecimalField(
        label="Mittagssnack Kinder", max_digits=6, decimal_places=2, min_value=0, required=False
    )
    snack_child_foerdersatz = SubsidyPercentField()

    def __init__(self, *args, **kwargs):
        self.camp = kwargs.pop("camp")
        super().__init__(*args, **kwargs)
        # Load initial values
        self.rules = {
            "breakfast": PriceRule.objects.filter(
                camp=self.camp, kind=PriceRule.Kind.MEAL, meal_type="breakfast", is_default=True, meal_date__isnull=True
            ),
            "snack": PriceRule.objects.filter(
                camp=self.camp, kind=PriceRule.Kind.MEAL, meal_type="snack", is_default=True, meal_date__isnull=True
            ),
            "dinner": PriceRule.objects.filter(
                camp=self.camp, kind=PriceRule.Kind.MEAL, meal_type="dinner", is_default=True, meal_date__isnull=True
            ),
        }
        for meal_type, qs in self.rules.items():
            for rule in qs:
                if rule.applies_to_adults:
                    self.initial[f"{meal_type}_adult_price"] = rule.unit_price
                    self.initial[f"{meal_type}_adult_foerdersatz"] = subsidy_percentage(rule.foerdersatz)
                if rule.applies_to_children:
                    self.initial[f"{meal_type}_child_price"] = rule.unit_price
                    self.initial[f"{meal_type}_child_foerdersatz"] = subsidy_percentage(rule.foerdersatz)

    def save(self):
        with transaction.atomic():
            for meal_type in ["breakfast", "snack", "dinner"]:
                adult_price = self.cleaned_data.get(f"{meal_type}_adult_price")
                adult_subsidy_rate = self.cleaned_data.get(f"{meal_type}_adult_foerdersatz")
                child_price = self.cleaned_data.get(f"{meal_type}_child_price")
                child_subsidy_rate = self.cleaned_data.get(f"{meal_type}_child_foerdersatz")

                if adult_price is not None:
                    PriceRule.objects.update_or_create(
                        camp=self.camp,
                        kind=PriceRule.Kind.MEAL,
                        meal_type=meal_type,
                        is_default=True,
                        applies_to_adults=True,
                        meal_date__isnull=True,
                        defaults={
                            "name": f"Standard {dict(PriceRule.MealType.choices).get(meal_type)}",
                            "unit_price": adult_price,
                            "foerdersatz": adult_subsidy_rate,
                            "applies_to_children": False,
                            "applies_to_companions": True,  # adults include companions for now
                        },
                    )
                if child_price is not None:
                    PriceRule.objects.update_or_create(
                        camp=self.camp,
                        kind=PriceRule.Kind.MEAL,
                        meal_type=meal_type,
                        is_default=True,
                        applies_to_children=True,
                        meal_date__isnull=True,
                        defaults={
                            "name": f"Standard {dict(PriceRule.MealType.choices).get(meal_type)} (Kind)",
                            "unit_price": child_price,
                            "foerdersatz": child_subsidy_rate,
                            "applies_to_adults": False,
                            "applies_to_companions": False,
                        },
                    )


class ShiftForm(forms.ModelForm):
    class Meta:
        model = Shift
        fields = ["name", "date", "start_time", "end_time", "required_slots"]
        labels = {
            "name": "Name des Dienstes",
            "date": "Datum",
            "start_time": "Startzeit",
            "end_time": "Endzeit",
            "required_slots": "Benötigte Helfer",
        }
        widgets = {
            "date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }


class DailyShiftTemplateForm(forms.ModelForm):
    class Meta:
        model = DailyShiftTemplate
        fields = ["name", "required_slots", "start_time", "end_time"]
        labels = {
            "name": "Bezeichnung",
            "required_slots": "Benötigte Personen",
            "start_time": "Startzeit",
            "end_time": "Endzeit",
        }
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }
