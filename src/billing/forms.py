from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Camp, Charge, Expense, Participant, Payment, PriceRule


class FirstAdminSetupForm(UserCreationForm):
    email = forms.EmailField(required=True)

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
        fields = ["name", "year", "starts_on", "ends_on", "is_active", "notes"]
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
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
            "booked_nights",
            "actual_nights",
            "notes",
        ]


class PriceRuleForm(forms.ModelForm):
    class Meta:
        model = PriceRule
        fields = ["kind", "name", "unit_price", "applies_to_children", "applies_to_adults", "is_default"]


class ChargeForm(forms.ModelForm):
    class Meta:
        model = Charge
        fields = ["kind", "description", "quantity", "unit_price", "occurred_on"]
        widgets = {"occurred_on": forms.DateInput(attrs={"type": "date"})}


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["amount", "paid_on", "method", "note"]
        widgets = {"paid_on": forms.DateInput(attrs={"type": "date"})}


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["participant", "category", "description", "amount", "paid_on", "reimbursable"]
        widgets = {"paid_on": forms.DateInput(attrs={"type": "date"})}


class ParticipantImportForm(forms.Form):
    file = forms.FileField(help_text="CSV oder XLSX mit Spalten first_name und last_name")
