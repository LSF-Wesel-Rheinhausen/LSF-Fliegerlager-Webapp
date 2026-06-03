from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Camp(TimeStampedModel):
    name = models.CharField(max_length=160)
    year = models.PositiveIntegerField()
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    foerdersatz = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal("0.5000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
        help_text="0 bis 1, zum Beispiel 0,5000 fuer 50 Prozent.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-year", "name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "year"], name="unique_camp_name_year"),
        ]

    def __str__(self):
        return f"{self.name} ({self.year})"


class Participant(TimeStampedModel):
    class Status(models.TextChoices):
        REGISTERED = "registered", "Angemeldet"
        ACTIVE = "active", "Aktiv"
        SETTLED = "settled", "Abgerechnet"
        CANCELLED = "cancelled", "Storniert"

    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="participants")
    first_name = models.CharField(max_length=120)
    last_name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REGISTERED)
    is_child = models.BooleanField(default=False)
    is_youth_group = models.BooleanField(default=False)
    is_companion = models.BooleanField(default=False)
    hilfssatz = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal("1.0000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
        help_text="0 bis 1, zum Beispiel 0,5000.",
    )
    berufssatz = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal("1.0000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
        help_text="0 bis 1, zum Beispiel 0,3300.",
    )
    booked_nights = models.PositiveIntegerField(default=0)
    actual_nights = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["camp", "first_name", "last_name"],
                name="unique_participant_name_per_camp",
            ),
        ]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.full_name


class ParticipantPin(TimeStampedModel):
    participant = models.OneToOneField(Participant, on_delete=models.CASCADE, related_name="pin")
    pin_hash = models.CharField(max_length=256, blank=True)
    must_set_pin = models.BooleanField(default=True)
    changed_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="changed_participant_pins",
    )

    def set_pin(self, raw_pin, changed_by=None):
        self.pin_hash = make_password(raw_pin)
        self.must_set_pin = False
        self.changed_by = changed_by

    def reset_pin(self, changed_by=None):
        self.pin_hash = ""
        self.must_set_pin = True
        self.changed_by = changed_by

    def check_pin(self, raw_pin):
        if not self.pin_hash:
            return False
        return check_password(raw_pin, self.pin_hash)

    def __str__(self):
        return f"PIN {self.participant}"


class PriceRule(TimeStampedModel):
    class Kind(models.TextChoices):
        CAMP_FLAT = "camp_flat", "Lagerpauschale"
        NIGHT = "night", "Übernachtung"
        MEAL = "meal", "Verpflegung"
        DRINK = "drink", "Getränk"
        OTHER = "other", "Sonstiges"

    class MealType(models.TextChoices):
        BREAKFAST = "breakfast", "Frühstück"
        DINNER = "dinner", "Abendessen"

    class CampFlatDuration(models.TextChoices):
        ONE_WEEK = "1w", "1 Woche"
        TWO_WEEKS = "2w", "2 Wochen"

    class CampFlatRole(models.TextChoices):
        PARTICIPANT = "participant", "Teilnehmer"
        COMPANION = "companion", "Begleitperson"

    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="price_rules")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    name = models.CharField(max_length=120)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    camp_flat_duration = models.CharField(max_length=2, choices=CampFlatDuration.choices, blank=True)
    camp_flat_role = models.CharField(max_length=20, choices=CampFlatRole.choices, blank=True)
    meal_type = models.CharField(max_length=20, choices=MealType.choices, blank=True)
    meal_date = models.DateField(null=True, blank=True)
    applies_to_children = models.BooleanField(default=True)
    applies_to_adults = models.BooleanField(default=True)
    applies_to_companions = models.BooleanField(default=True)
    foerderfaehig = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["kind", "name"]

    def __str__(self):
        return f"{self.camp}: {self.name}"


class Charge(TimeStampedModel):
    class Kind(models.TextChoices):
        CAMP_FLAT = "camp_flat", "Lagerpauschale"
        FOOD = "food", "Verpflegung"
        DRINK = "drink", "Getränke"
        OTHER = "other", "Sonstige Kosten"

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="charges")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    description = models.CharField(max_length=180)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1.00"))
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    foerderfaehig = models.BooleanField(default=True)
    occurred_on = models.DateField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_charges",
    )

    class Meta:
        ordering = ["participant", "kind", "description"]

    @property
    def total(self):
        return self.quantity * self.unit_price

    @property
    def booking_reference(self) -> str:
        """Return the human-readable booking identifier."""
        if self.pk is None:
            return ""
        return f"B#{self.pk:05d}"

    def __str__(self):
        return f"{self.booking_reference} {self.participant}: {self.description}"


class BookingAuditLog(models.Model):
    class Action(models.TextChoices):
        UPDATED = "updated", "Bearbeitet"
        DELETED = "deleted", "Gelöscht"
        RESTORED = "restored", "Wiederhergestellt"

    participant = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booking_audit_logs",
    )
    charge = models.ForeignKey(Charge, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    changed_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booking_audit_logs",
    )
    action = models.CharField(max_length=20, choices=Action.choices, default=Action.UPDATED)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.charge}: {self.get_action_display()} am {self.created_at:%Y-%m-%d %H:%M}"


class Payment(TimeStampedModel):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=180, blank=True)

    class Meta:
        ordering = ["-paid_on", "participant"]

    def __str__(self):
        return f"{self.participant}: {self.amount}"


class Expense(TimeStampedModel):
    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="expenses")
    participant = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name="expenses",
        null=True,
        blank=True,
        help_text="Optional, wenn ein Teilnehmer den Betrag vorgestreckt hat.",
    )
    category = models.CharField(max_length=120)
    description = models.CharField(max_length=180)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_on = models.DateField(null=True, blank=True)
    reimbursable = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "description"]

    def __str__(self):
        return f"{self.camp}: {self.description}"


class MealSignup(TimeStampedModel):
    class Meal(models.TextChoices):
        BREAKFAST = "breakfast", "Frühstück"
        DINNER = "dinner", "Abendessen"

    class Variant(models.TextChoices):
        NORMAL = "normal", "Normal"
        VEGAN = "vegan", "Vegan"
        NORMAL_CHILD = "normal_child", "Normal Kind"
        VEGAN_CHILD = "vegan_child", "Vegan Kind"

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="meal_signups")
    meal_date = models.DateField()
    meal = models.CharField(max_length=20, choices=Meal.choices)
    variant = models.CharField(max_length=20, choices=Variant.choices)
    foerderfaehig = models.BooleanField(default=True)

    class Meta:
        ordering = ["meal_date", "meal", "participant"]
        constraints = [
            models.UniqueConstraint(fields=["participant", "meal_date", "meal"], name="unique_meal_signup"),
        ]

    def __str__(self):
        return f"{self.participant}: {self.meal_date} {self.meal}"


class DrinkEntry(TimeStampedModel):
    class Drink(models.TextChoices):
        ICED_TEA = "iced_tea", "Eistee"
        SOFTDRINK = "softdrink", "Softdrink"
        WATER = "water", "Wasser"
        BEER = "beer", "Bier"

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="drink_entries")
    drink = models.CharField(max_length=20, choices=Drink.choices)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    foerderfaehig = models.BooleanField(default=True)
    booked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-booked_at", "participant"]

    @property
    def total(self):
        return Decimal(self.quantity) * self.unit_price

    def __str__(self):
        return f"{self.participant}: {self.get_drink_display()} x {self.quantity}"


class Settlement(TimeStampedModel):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="settlements")
    calculated_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    total_due = models.DecimalField(max_digits=10, decimal_places=2)
    total_paid = models.DecimalField(max_digits=10, decimal_places=2)
    total_advanced = models.DecimalField(max_digits=10, decimal_places=2)
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ["participant", "-created_at"]

    def __str__(self):
        return f"{self.participant}: {self.balance}"
