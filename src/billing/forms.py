from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db import transaction

from .models import Camp, Charge, Expense, MealSignup, Participant, ParticipantPin, Payment, PriceRule


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
            "foerderfaehig",
            "is_default",
        ]
        labels = {
            "kind": "Art",
            "name": "Name",
            "unit_price": "Einzelpreis",
            "camp_flat_duration": "Lagerpauschale für",
            "camp_flat_role": "Personengruppe",
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
    participant_1w_foerderfaehig = forms.BooleanField(label="Förderfähig", required=False)
    participant_2w_price = forms.DecimalField(label="Teilnehmer 2 Wochen", min_value=0, max_digits=10, decimal_places=2)
    participant_2w_foerderfaehig = forms.BooleanField(label="Förderfähig", required=False)
    companion_1w_price = forms.DecimalField(label="Begleitperson 1 Woche", min_value=0, max_digits=10, decimal_places=2)
    companion_1w_foerderfaehig = forms.BooleanField(label="Förderfähig", required=False)
    companion_2w_price = forms.DecimalField(
        label="Begleitperson 2 Wochen",
        min_value=0,
        max_digits=10,
        decimal_places=2,
    )
    companion_2w_foerderfaehig = forms.BooleanField(label="Förderfähig", required=False)

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
                self.fields[f"{prefix}_foerderfaehig"].initial = rule.foerderfaehig
            else:
                self.fields[f"{prefix}_price"].initial = 0
                self.fields[f"{prefix}_foerderfaehig"].initial = True

    def rows(self):
        return [
            {
                "role": role_label,
                "duration": duration_label,
                "price": self[f"{prefix}_price"],
                "foerderfaehig": self[f"{prefix}_foerderfaehig"],
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
                rule.foerderfaehig = self.cleaned_data[f"{prefix}_foerderfaehig"]
                rule.is_default = True
                rule.save()
                PriceRule.objects.filter(
                    camp=self.camp,
                    kind=PriceRule.Kind.CAMP_FLAT,
                    camp_flat_role=role,
                    camp_flat_duration=duration,
                ).exclude(pk=rule.pk).update(is_default=False)


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
