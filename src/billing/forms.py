from datetime import time
from decimal import Decimal
from typing import Any

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, UserCreationForm
from django.core.validators import FileExtensionValidator
from django.db import models, transaction

from .models import (
    Camp,
    Charge,
    DailyShiftTemplate,
    Expense,
    MealSignup,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    ParticipantPin,
    Payment,
    PriceRule,
    Shift,
    UserProfile,
)
from .roles import ROLE_ADMIN, ROLE_CHOICES, user_role

PERCENT_PLACES = Decimal("0.01")
MAX_IMPORT_FILE_SIZE = 5 * 1024 * 1024


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
        }
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
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
            "booked_nights": "Gebuchte Nächte",
            "actual_nights": "Tatsächliche Nächte",
            "notes": "Notizen",
        }
        widgets = {
            "hilfssatz": forms.NumberInput(attrs={"step": "0.0001", "min": "0", "max": "1"}),
            "berufssatz": forms.NumberInput(attrs={"step": "0.0001", "min": "0", "max": "1"}),
        }


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
        widgets = {"occurred_on": forms.DateInput(attrs={"type": "date"})}


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
        widgets = {"paid_on": forms.DateInput(attrs={"type": "date"})}


EXPENSE_CATEGORY_CHOICES = [
    ("Unterkunft/Verpflegung", "Unterkunft/Verpflegung"),
    ("Fahrtkosten", "Fahrtkosten"),
    ("Verbrauchsmaterial", "Verbrauchsmaterial"),
    ("Miete/sonstiges", "Miete/sonstiges"),
]


class ExpenseForm(forms.ModelForm):
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
            "paid_on": forms.DateInput(attrs={"type": "date"}),
            "category": forms.Select(choices=EXPENSE_CATEGORY_CHOICES),
            "receipt": forms.FileInput(
                attrs={
                    "accept": "application/pdf,image/jpeg,image/png,image/heic,.pdf,.jpg,.jpeg,.png,.heic",
                    "capture": "environment",
                }
            ),
        }


class SharedExpenseRequestForm(forms.ModelForm):
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
            "paid_on": forms.DateInput(attrs={"type": "date"}),
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
        max_length=12,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
    )


class KioskLoginForm(forms.Form):
    participant = forms.ModelChoiceField(label="Teilnehmer", queryset=Participant.objects.none())
    pin = forms.CharField(
        label="PIN",
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "inputmode": "numeric"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["participant"].queryset = Participant.objects.filter(
            camp__is_active=True, archived_at__isnull=True
        ).select_related("camp")
        self.missing_pin_participant = None

    def clean(self):
        cleaned_data = super().clean()
        participant = cleaned_data.get("participant")
        pin = cleaned_data.get("pin")
        if participant:
            try:
                participant_pin = participant.pin
            except ParticipantPin.DoesNotExist:
                participant_pin = None
            if participant_pin is None or participant_pin.must_set_pin or not participant_pin.pin_hash:
                self.missing_pin_participant = participant
                raise forms.ValidationError("Für diesen Teilnehmer ist noch kein PIN gesetzt.", code="missing_pin")
            if participant_pin.is_locked:
                raise forms.ValidationError(
                    "Zu viele Fehlversuche. Bitte warte fünf Minuten und versuche es erneut.", code="pin_locked"
                )
            if pin and not participant_pin.check_pin(pin):
                raise forms.ValidationError("Teilnehmer oder PIN ist ungültig.", code="invalid_pin")
        return cleaned_data


class KioskPinSetupForm(forms.Form):
    pin = forms.CharField(
        label="Neuer PIN",
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

    def clean(self):
        cleaned_data = super().clean()
        pin = cleaned_data.get("pin")
        pin_repeat = cleaned_data.get("pin_repeat")
        if pin and pin_repeat and pin != pin_repeat:
            raise forms.ValidationError("Die PINs stimmen nicht überein.", code="pin_mismatch")
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
        super().__init__(*args, **kwargs)
        if participant is not None:
            camp = participant.camp
        if camp is not None:
            queryset = PriceRule.objects.filter(
                camp=camp, kind__in=[PriceRule.Kind.DRINK, PriceRule.Kind.SNACK]
            ).order_by("name")
            if participant is not None:
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

    class Meta:
        model = ParticipantFamilyMember
        fields = ["first_name", "last_name", "role"]
        labels = {
            "first_name": "Vorname",
            "last_name": "Nachname",
            "role": "Rolle",
        }


class KioskBookingLinkInviteForm(forms.Form):
    """Invite another active camp participant for reciprocal kiosk booking."""

    participant = forms.ModelChoiceField(label="Teilnehmer einladen", queryset=Participant.objects.none())

    def __init__(self, *args, **kwargs):
        self.inviter = kwargs.pop("inviter")
        super().__init__(*args, **kwargs)
        self.fields["participant"].queryset = (
            Participant.objects.filter(camp=self.inviter.camp, camp__is_active=True, archived_at__isnull=True)
            .exclude(pk=self.inviter.pk)
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


class MealBookingForm(forms.Form):
    meal_date = forms.DateField(label="Datum", widget=forms.DateInput(attrs={"type": "date"}))
    meal = forms.ChoiceField(label="Mahlzeit", choices=MealSignup.Meal.choices)
    variant = forms.ChoiceField(label="Variante", choices=MealSignup.Variant.choices)

    def __init__(self, *args, **kwargs):
        participant = kwargs.pop("participant", None)
        kwargs.pop("camp", None)
        super().__init__(*args, **kwargs)
        if participant is not None:
            from django.utils import timezone

            self.fields["meal_date"].initial = timezone.now().date()
            if participant.is_child:
                self.fields["variant"].choices = [
                    (MealSignup.Variant.NORMAL_CHILD, "Mit Fleisch (Kind)"),
                    (MealSignup.Variant.VEGAN_CHILD, "Vegan/Vegetarisch (Kind)"),
                ]
            else:
                self.fields["variant"].choices = [
                    (MealSignup.Variant.NORMAL, "Mit Fleisch"),
                    (MealSignup.Variant.VEGAN, "Vegan/Vegetarisch"),
                ]


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

    def __init__(self, *args, **kwargs):
        self.camp = kwargs.pop("camp")
        super().__init__(*args, **kwargs)
        # Load initial values
        self.rules = {
            "breakfast": PriceRule.objects.filter(
                camp=self.camp, kind=PriceRule.Kind.MEAL, meal_type="breakfast", is_default=True, meal_date__isnull=True
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
            for meal_type in ["breakfast", "dinner"]:
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
            "date": forms.DateInput(attrs={"type": "date"}),
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
