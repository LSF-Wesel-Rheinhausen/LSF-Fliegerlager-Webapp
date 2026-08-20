"""Narrow kiosk forms for personal contact-data updates."""

from __future__ import annotations

from datetime import date
from typing import Any

from django import forms

from .models import Participant, ParticipantFamilyMember

PROFILE_FIELDS = ("first_name", "last_name", "email", "phone", "birth_date")


class _ProfileForm(forms.ModelForm):
    """Share validation and persistence rules for kiosk profile forms."""

    class Meta:
        fields = PROFILE_FIELDS
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"})}

    def add_error(self, field: str | None, error: Any) -> None:
        """Expose server-side field errors to assistive technologies."""
        super().add_error(field, error)
        if field is None or field not in self.fields:
            return
        self.fields[field].widget.attrs.update(
            {
                "aria-describedby": f"id_{field}_error",
                "aria-invalid": "true",
            }
        )

    def clean(self) -> dict[str, Any]:
        """Normalize names and reject invalid dates and participant-name collisions."""
        cleaned_data = super().clean() or {}
        for field_name in ("first_name", "last_name"):
            value = cleaned_data.get(field_name)
            if value is not None:
                normalized = value.strip()
                cleaned_data[field_name] = normalized
                if not normalized:
                    self.add_error(field_name, "Dieses Feld darf nicht leer sein.")

        birth_date = cleaned_data.get("birth_date")
        if birth_date is not None and birth_date > date.today():
            self.add_error("birth_date", "Das Geburtsdatum darf nicht in der Zukunft liegen.")

        first_name = cleaned_data.get("first_name")
        last_name = cleaned_data.get("last_name")
        if first_name and last_name:
            camp_id = (
                self.instance.camp_id if isinstance(self.instance, Participant) else self.instance.guardian.camp_id
            )
            collisions = Participant.objects.filter(
                camp_id=camp_id,
                first_name__iexact=first_name,
                last_name__iexact=last_name,
            )
            if isinstance(self.instance, Participant):
                collisions = collisions.exclude(pk=self.instance.pk)
            if collisions.exists():
                self.add_error("first_name", "Dieser Name ist in diesem Fliegerlager bereits vergeben.")
        return cleaned_data

    @property
    def changed_field_names(self) -> list[str]:
        """Return the permitted fields that actually differ from the persisted profile."""
        return [field_name for field_name in PROFILE_FIELDS if field_name in self.changed_data]

    def save(self, commit: bool = True):
        """Persist only the allow-listed profile attributes."""
        if not self.is_valid():
            raise ValueError("Ein ungültiges Profilformular kann nicht gespeichert werden.")
        for field_name in PROFILE_FIELDS:
            setattr(self.instance, field_name, self.cleaned_data[field_name])
        if commit and self.changed_field_names:
            self.instance.save(update_fields=[*self.changed_field_names, "updated_at"])
        return self.instance


class ParticipantProfileForm(_ProfileForm):
    """Edit only a primary participant's personal contact data."""

    class Meta(_ProfileForm.Meta):
        model = Participant


class ParticipantFamilyMemberProfileForm(_ProfileForm):
    """Edit only a guardian-owned family member's personal contact data."""

    class Meta(_ProfileForm.Meta):
        model = ParticipantFamilyMember
