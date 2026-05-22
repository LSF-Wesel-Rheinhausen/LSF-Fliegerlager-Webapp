from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import (
    Camp,
    Charge,
    Expense,
    MealSignup,
    OvernightCategory,
    Participant,
    ParticipantPin,
    Payment,
    PriceRule,
)


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Benutzername oder E-Mail")
    password = forms.CharField(label="Passwort", strip=False, widget=forms.PasswordInput)


class FirstAdminSetupForm(UserCreationForm):
    username = forms.CharField(label="Benutzername")
    email = forms.EmailField(label="E-Mail-Adresse", required=True)
    password1 = forms.CharField(label="Passwort", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Passwort wiederholen", strip=False, widget=forms.PasswordInput)

    class Meta:
        model = get_user_model()
        fields = ["username", "email"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.is_staff = True
        user.is_superuser = True
        if commit:
            user.save()
        return user


class CampForm(forms.ModelForm):
    class Meta:
        model = Camp
        fields = ["name", "year", "starts_on", "ends_on", "is_active", "foerdersatz", "notes"]
        labels = {
            "name": "Name",
            "year": "Jahr",
            "starts_on": "Beginn",
            "ends_on": "Ende",
            "is_active": "Aktiv",
            "foerdersatz": "Fördersatz",
            "notes": "Notizen",
        }
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
            "foerdersatz": forms.NumberInput(attrs={"step": "0.0001", "min": "0", "max": "1"}),
        }


class ParticipantForm(forms.ModelForm):
    def __init__(self, *args, camp=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.camp = camp or getattr(self.instance, "camp", None)
        category_queryset = OvernightCategory.objects.none()
        participant_queryset = Participant.objects.none()
        if self.camp is not None:
            category_queryset = OvernightCategory.objects.filter(camp=self.camp, is_active=True).order_by("name")
            participant_queryset = Participant.objects.filter(camp=self.camp).order_by("last_name", "first_name")
            if self.instance.pk:
                participant_queryset = participant_queryset.exclude(pk=self.instance.pk)
        self.fields["overnight_category"].queryset = category_queryset
        self.fields["overnight_category"].required = True
        self.fields["primary_participant"].queryset = participant_queryset

    def clean(self):
        if self.camp is not None:
            self.instance.camp = self.camp
        return super().clean()

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
            "primary_participant",
            "overnight_category",
            "arrival_date",
            "departure_date",
            "hilfssatz",
            "berufssatz",
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
            "primary_participant": "Hauptperson",
            "overnight_category": "Uebernachtungskategorie",
            "arrival_date": "Anreise",
            "departure_date": "Abreise",
            "hilfssatz": "Hilfssatz",
            "berufssatz": "Berufssatz",
            "notes": "Notizen",
        }
        widgets = {
            "arrival_date": forms.DateInput(attrs={"type": "date"}),
            "departure_date": forms.DateInput(attrs={"type": "date"}),
            "hilfssatz": forms.NumberInput(attrs={"step": "0.0001", "min": "0", "max": "1"}),
            "berufssatz": forms.NumberInput(attrs={"step": "0.0001", "min": "0", "max": "1"}),
        }


class PriceRuleForm(forms.ModelForm):
    compact_kinds = {PriceRule.Kind.DRINK, PriceRule.Kind.MEAL}
    supported_overlay_kinds = {
        PriceRule.Kind.CAMP_FLAT,
        PriceRule.Kind.NIGHT,
        PriceRule.Kind.MEAL,
        PriceRule.Kind.DRINK,
        PriceRule.Kind.OTHER,
    }

    class Meta:
        model = PriceRule
        fields = [
            "kind",
            "name",
            "unit_price",
            "overnight_category",
            "camp_flat_duration",
            "camp_flat_role",
            "applies_to_children",
            "applies_to_adults",
            "foerderfaehig",
            "is_default",
        ]
        labels = {
            "kind": "Art",
            "name": "Name",
            "unit_price": "Einzelpreis",
            "overnight_category": "Uebernachtungskategorie",
            "camp_flat_duration": "Alte Dauerzuordnung",
            "camp_flat_role": "Alte Rollenzuordnung",
            "applies_to_children": "Gilt für Kinder",
            "applies_to_adults": "Gilt für Erwachsene",
            "foerderfaehig": "Förderfähig",
            "is_default": "Standardregel",
        }
        widgets = {
            "kind": forms.RadioSelect,
            "camp_flat_duration": forms.RadioSelect,
            "camp_flat_role": forms.RadioSelect,
        }

    def __init__(self, *args, fixed_kind=None, camp=None, **kwargs):
        super().__init__(*args, **kwargs)
        instance_kind = getattr(self.instance, "kind", "")
        self.fixed_kind = fixed_kind or instance_kind or ""
        self.camp = camp or getattr(self.instance, "camp", None)

        category_queryset = OvernightCategory.objects.none()
        if self.camp is not None:
            category_queryset = OvernightCategory.objects.filter(camp=self.camp, is_active=True).order_by("name")
        self.fields["overnight_category"].queryset = category_queryset

        if self.fixed_kind:
            self.fields.pop("kind", None)
            self.initial["kind"] = self.fixed_kind

        if self.active_kind != PriceRule.Kind.CAMP_FLAT:
            self.fields.pop("overnight_category", None)
            self.fields.pop("camp_flat_duration", None)
            self.fields.pop("camp_flat_role", None)

        if not self.is_bound and not self.instance.pk and self.active_kind in self.compact_kinds:
            self.fields["applies_to_children"].initial = True
            self.fields["applies_to_adults"].initial = True
            self.fields["is_default"].initial = False

    @property
    def active_kind(self):
        return self.fixed_kind or self.initial.get("kind") or getattr(self.instance, "kind", "")

    @property
    def is_compact(self):
        return self.active_kind in self.compact_kinds

    @property
    def category_label(self):
        if not self.active_kind:
            return "Preisregel"
        return PriceRule.Kind(self.active_kind).label

    @property
    def basic_fields(self):
        if self.active_kind == PriceRule.Kind.CAMP_FLAT:
            names = ["name", "overnight_category", "unit_price", "foerderfaehig"]
        elif self.is_compact:
            names = ["name", "unit_price", "foerderfaehig"]
        else:
            names = [
                "name",
                "unit_price",
                "foerderfaehig",
                "is_default",
                "applies_to_children",
                "applies_to_adults",
            ]
        return [self[name] for name in names if name in self.fields]

    @property
    def advanced_fields(self):
        if not self.is_compact:
            return []
        names = ["is_default", "applies_to_children", "applies_to_adults"]
        return [self[name] for name in names if name in self.fields]

    @property
    def advanced_collapsed(self):
        return self.is_compact

    def clean(self):
        cleaned_data = super().clean()
        kind = self.fixed_kind or cleaned_data.get("kind")
        cleaned_data["kind"] = kind
        if kind == PriceRule.Kind.CAMP_FLAT:
            if not cleaned_data.get("overnight_category"):
                self.add_error("overnight_category", "Bitte eine Uebernachtungskategorie auswählen.")
        else:
            cleaned_data["overnight_category"] = None
            cleaned_data["camp_flat_duration"] = ""
            cleaned_data["camp_flat_role"] = ""
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.fixed_kind:
            instance.kind = self.fixed_kind
        if commit:
            instance.save()
        return instance


class OvernightCategoryForm(forms.ModelForm):
    class Meta:
        model = OvernightCategory
        fields = ["name", "description", "is_active"]
        labels = {
            "name": "Name",
            "description": "Beschreibung",
            "is_active": "Aktiv",
        }


class ChargeForm(forms.ModelForm):
    class Meta:
        model = Charge
        fields = ["kind", "description", "quantity", "unit_price", "foerderfaehig", "occurred_on"]
        labels = {
            "kind": "Art",
            "description": "Beschreibung",
            "quantity": "Menge",
            "unit_price": "Einzelpreis",
            "foerderfaehig": "Förderfähig",
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


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["participant", "category", "description", "amount", "paid_on", "reimbursable"]
        labels = {
            "participant": "Teilnehmer",
            "category": "Kategorie",
            "description": "Beschreibung",
            "amount": "Betrag",
            "paid_on": "Zahlungsdatum",
            "reimbursable": "Erstattungsfähig",
        }
        widgets = {"paid_on": forms.DateInput(attrs={"type": "date"})}


class ParticipantImportForm(forms.Form):
    file = forms.FileField(
        label="Importdatei",
        help_text="CSV oder XLSX mit den Spalten first_name, last_name, hilfssatz und berufssatz",
    )


class ParticipantPinForm(forms.Form):
    pin = forms.CharField(label="Neue PIN", min_length=4, max_length=12, strip=True, widget=forms.PasswordInput)


class KioskLoginForm(forms.Form):
    participant = forms.ModelChoiceField(label="Teilnehmer", queryset=Participant.objects.none())
    pin = forms.CharField(label="PIN", strip=True, widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["participant"].queryset = Participant.objects.filter(camp__is_active=True).select_related("camp")
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
            if pin and not participant_pin.check_pin(pin):
                raise forms.ValidationError("Teilnehmer oder PIN ist ungültig.", code="invalid_pin")
        return cleaned_data


class KioskPinSetupForm(forms.Form):
    pin = forms.CharField(label="Neuer PIN", min_length=4, max_length=12, strip=True, widget=forms.PasswordInput)
    pin_repeat = forms.CharField(
        label="PIN wiederholen",
        min_length=4,
        max_length=12,
        strip=True,
        widget=forms.PasswordInput,
    )

    def clean(self):
        cleaned_data = super().clean()
        pin = cleaned_data.get("pin")
        pin_repeat = cleaned_data.get("pin_repeat")
        if pin and pin_repeat and pin != pin_repeat:
            raise forms.ValidationError("Die PINs stimmen nicht überein.", code="pin_mismatch")
        return cleaned_data


class KioskStayForm(forms.ModelForm):
    class Meta:
        model = Participant
        fields = ["overnight_category", "arrival_date", "departure_date"]
        labels = {
            "overnight_category": "Uebernachtungskategorie",
            "arrival_date": "Anreise",
            "departure_date": "Abreise",
        }
        widgets = {
            "arrival_date": forms.DateInput(attrs={"type": "date"}),
            "departure_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, camp=None, **kwargs):
        super().__init__(*args, **kwargs)
        resolved_camp = camp or getattr(self.instance, "camp", None)
        self.fields["overnight_category"].queryset = OvernightCategory.objects.filter(
            camp=resolved_camp,
            is_active=True,
        ).order_by("name")
        self.fields["overnight_category"].required = True


class KioskLinkedParticipantForm(forms.ModelForm):
    participant_type = forms.ChoiceField(
        label="Typ",
        choices=[
            ("companion", "Begleitperson"),
            ("child", "Kind"),
        ],
    )

    class Meta:
        model = Participant
        fields = [
            "first_name",
            "last_name",
            "participant_type",
            "overnight_category",
            "arrival_date",
            "departure_date",
            "notes",
        ]
        labels = {
            "first_name": "Vorname",
            "last_name": "Nachname",
            "overnight_category": "Uebernachtungskategorie",
            "arrival_date": "Anreise",
            "departure_date": "Abreise",
            "notes": "Notiz",
        }
        widgets = {
            "arrival_date": forms.DateInput(attrs={"type": "date"}),
            "departure_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, camp=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.camp = camp or getattr(self.instance, "camp", None)
        self.fields["overnight_category"].queryset = OvernightCategory.objects.filter(
            camp=self.camp,
            is_active=True,
        ).order_by("name")
        self.fields["overnight_category"].required = True

    def clean(self):
        if self.camp is not None:
            self.instance.camp = self.camp
        return super().clean()

    def save(self, commit=True):
        participant = super().save(commit=False)
        participant_type = self.cleaned_data["participant_type"]
        participant.is_companion = participant_type == "companion"
        participant.is_child = participant_type == "child"
        if commit:
            participant.save()
        return participant


class DrinkBookingForm(forms.Form):
    price_rule = forms.ModelChoiceField(label="Getränk", queryset=PriceRule.objects.none())
    quantity = forms.IntegerField(
        label="Menge",
        min_value=1,
        max_value=99,
        initial=1,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": "1", "max": "99", "step": "1"}),
    )

    def __init__(self, *args, **kwargs):
        camp = kwargs.pop("camp", None)
        super().__init__(*args, **kwargs)
        if camp is not None:
            queryset = PriceRule.objects.filter(camp=camp, kind=PriceRule.Kind.DRINK).order_by("name")
            self.fields["price_rule"].queryset = queryset
        self.fields["price_rule"].label_from_instance = lambda rule: f"{rule.name} - {rule.unit_price} EUR"


class MealBookingForm(forms.Form):
    price_rule = forms.ModelChoiceField(label="Essen", queryset=PriceRule.objects.none())
    meal_date = forms.DateField(label="Datum", widget=forms.DateInput(attrs={"type": "date"}))
    meal = forms.ChoiceField(label="Mahlzeit", choices=MealSignup.Meal.choices)
    variant = forms.ChoiceField(label="Variante", choices=MealSignup.Variant.choices)

    def __init__(self, *args, **kwargs):
        camp = kwargs.pop("camp", None)
        super().__init__(*args, **kwargs)
        if camp is not None:
            queryset = PriceRule.objects.filter(camp=camp, kind=PriceRule.Kind.MEAL).order_by("name")
            self.fields["price_rule"].queryset = queryset
        self.fields["price_rule"].label_from_instance = lambda rule: f"{rule.name} - {rule.unit_price} EUR"
