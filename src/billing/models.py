from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """
    Abstract base model providing automatic timestamps for creation and updates.

    This model is used across domain entities to ensure traceability of
    when records were created and last modified, which is crucial for
    auditing financial and participant data.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Camp(TimeStampedModel):
    """
    Represents a specific camp session.

    This model holds the high-level metadata for a camp, such as its name,
    duration, and the general subsidy rate (foerdersatz) applied to the camp.
    It serves as the parent entity for all participants, prices, and charges.
    """
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
        help_text="0 bis 1, zum Beispiel 0,5000 fuer 50 Prozent. Dies bestimmt den allgemeinen Zuschuss.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-year", "name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "year"], name="unique_camp_name_year"),
        ]

    def __str__(self):
        """
        Returns a user-friendly string representation of the Camp.

        Returns:
            str: The name of the camp followed by its year.
        """
        return f"{self.name} ({self.year})"


class OvernightCategory(TimeStampedModel):
    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="overnight_categories")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["camp", "name"], name="unique_overnight_category_name_per_camp"),
        ]

    def __str__(self):
        return f"{self.camp}: {self.name}"


class Participant(TimeStampedModel):
    """
    Represents an individual participant registered for a Camp.

    This model stores all demographic and registration data, along with
    specific financial and status flags (like hilfssatz and berufssatz)
    that affect their final settlement calculation.
    """
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
    primary_participant = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="linked_participants",
        null=True,
        blank=True,
    )
    overnight_category = models.ForeignKey(
        OvernightCategory,
        on_delete=models.PROTECT,
        related_name="participants",
        null=True,
        blank=True,
    )
    hilfssatz = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal("1.0000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
        help_text="0 bis 1, zum Beispiel 0,5000. Der Hilfssatz reduziert die Kosten des Teilnehmers.",
    )
    berufssatz = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal("1.0000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
        help_text="0 bis 1, zum Beispiel 0,3300. Der Berufssatz reduziert die Kosten basierend auf dem Status.",
    )
    arrival_date = models.DateField(null=True, blank=True)
    departure_date = models.DateField(null=True, blank=True)
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
        """
        Calculates the full name of the participant.

        This property is used for display purposes across the application (e.g., in lists and forms).

        Returns:
            str: The concatenated first and last name.
        """
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def stay_nights(self):
        if self.arrival_date and self.departure_date:
            return max((self.departure_date - self.arrival_date).days, 0)
        return None

    @property
    def effective_nights(self):
        if self.stay_nights is not None:
            return self.stay_nights
        return self.actual_nights or self.booked_nights or 0

    def clean(self):
        super().clean()
        if self.arrival_date and self.departure_date and self.departure_date < self.arrival_date:
            raise ValidationError({"departure_date": "Die Abreise muss nach der Anreise liegen."})
        if self.overnight_category and self.overnight_category.camp_id != self.camp_id:
            raise ValidationError(
                {"overnight_category": "Die Uebernachtungskategorie muss zum gleichen Lager gehoeren."}
            )
        if self.primary_participant:
            if self.primary_participant_id == self.pk:
                raise ValidationError({"primary_participant": "Eine Person kann nicht sich selbst zugeordnet werden."})
            if self.primary_participant.camp_id != self.camp_id:
                raise ValidationError({"primary_participant": "Die Hauptperson muss zum gleichen Lager gehoeren."})

    def save(self, *args, **kwargs):
        if self.stay_nights is not None:
            self.actual_nights = self.stay_nights
        super().save(*args, **kwargs)

    def __str__(self):
        """
        Returns the full name of the participant as a string.

        Returns:
            str: The participant's full name.
        """
        return self.full_name


class ParticipantPin(TimeStampedModel):
    """
    Stores the PIN for a specific participant, enabling kiosk or self-service access.

    This model securely hashes the user-provided PIN and tracks who last
    modified the PIN, ensuring accountability.
    """
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

    def set_pin(self, raw_pin: str, changed_by=None):
        """
        Hashes and sets a new PIN for the participant.

        This method is used when the participant or an administrator sets the initial PIN.
        It securely hashes the raw PIN using Django's password hashing mechanism.

        Args:
            raw_pin (str): The plaintext PIN provided by the user.
            changed_by (User): The user object responsible for the change.
        """
        self.pin_hash = make_password(raw_pin)
        self.must_set_pin = False
        self.changed_by = changed_by

    def reset_pin(self, changed_by=None):
        """
        Resets the participant's PIN, requiring a new PIN to be set.

        This is used when a PIN is lost or needs to be changed administratively.

        Args:
            changed_by (User): The user object responsible for the change.
        """
        self.pin_hash = ""
        self.must_set_pin = True
        self.changed_by = changed_by

    def check_pin(self, raw_pin: str) -> bool:
        """
        Verifies a raw PIN against the stored hash.

        This is the primary method used by kiosk interfaces to authenticate participants.

        Args:
            raw_pin (str): The plaintext PIN entered by the participant.

        Returns:
            bool: True if the PIN matches the stored hash, False otherwise (or if no PIN is set).
        """
        if not self.pin_hash:
            return False
        return check_password(raw_pin, self.pin_hash)

    def __str__(self):
        """
        Returns a string representation of the PIN entry.

        Returns:
            str: A string identifying the PIN entry and its associated participant.
        """
        return f"PIN {self.participant}"


class PriceRule(TimeStampedModel):
    """
    Defines a specific pricing rule within a Camp.

    PriceRules dictate the cost structure for various services (e.g., camp flat rate, meal, drink)
    and can specify how these rules apply to different roles (Participant/Companion)
    and whether they are subsidized (foerderfaehig).
    """
    class Kind(models.TextChoices):
        CAMP_FLAT = "camp_flat", "Lagerpauschale"
        NIGHT = "night", "Übernachtung"
        MEAL = "meal", "Verpflegung"
        DRINK = "drink", "Getränk"
        OTHER = "other", "Sonstiges"

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
    overnight_category = models.ForeignKey(
        OvernightCategory,
        on_delete=models.PROTECT,
        related_name="price_rules",
        null=True,
        blank=True,
    )
    camp_flat_duration = models.CharField(max_length=2, choices=CampFlatDuration.choices, blank=True)
    camp_flat_role = models.CharField(max_length=20, choices=CampFlatRole.choices, blank=True)
    applies_to_children = models.BooleanField(default=True)
    applies_to_adults = models.BooleanField(default=True)
    foerderfaehig = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["kind", "name"]

    def __str__(self):
        """
        Returns a string representation of the Price Rule.

        Returns:
            str: A descriptive string including the camp and rule name.
        """
        return f"{self.camp}: {self.name}"


class Charge(TimeStampedModel):
    """
    Represents a specific cost or charge applied to a Participant.

    Charges are the detailed line items that contribute to the participant's
    total bill. They can be generated from PriceRules or manually entered.
    """
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

    class Meta:
        ordering = ["participant", "kind", "description"]

    @property
    def total(self):
        """
        Calculates the total cost for this charge.

        Returns:
            Decimal: The total amount (quantity * unit_price).
        """
        return self.quantity * self.unit_price

    def __str__(self):
        """
        Returns a string representation of the Charge.

        Returns:
            str: A descriptive string including the participant and charge description.
        """
        return f"{self.participant}: {self.description}"


class Payment(TimeStampedModel):
    """
    Records a payment made by a participant or their representative.

    This model tracks how much money has been paid towards the total bill,
    allowing the system to calculate the remaining balance.
    """
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=180, blank=True)

    class Meta:
        ordering = ["-paid_on", "participant"]

    def __str__(self):
        """
        Returns a string representation of the Payment record.

        Returns:
            str: A descriptive string including the participant and payment amount.
        """
        return f"{self.participant}: {self.amount}"


class Expense(TimeStampedModel):
    """
    Tracks expenses incurred by the camp or participants that require reimbursement.

    This model is used for tracking costs that need to be allocated back
    to the camp or participants.
    """
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
        """
        Returns a string representation of the Expense record.

        Returns:
            str: A descriptive string including the camp and expense description.
        """
        return f"{self.camp}: {self.description}"


class MealSignup(TimeStampedModel):
    """
    Records a participant's meal preference for a specific date.

    This model is essential for the catering and logistics side of the camp,
    allowing for accurate planning and subsequent cost calculation.
    """
    class Meal(models.TextChoices):
        BREAKFAST = "breakfast", "Frühstück"
        LUNCH = "lunch", "Mittagessen"
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
        """
        Returns a string representation of the Meal Signup.

        Returns:
            str: A descriptive string including the participant, date, and meal type.
        """
        return f"{self.participant}: {self.meal_date} {self.meal}"


class DrinkEntry(TimeStampedModel):
    """
    Records an individual drink consumption event by a participant.

    This model tracks specific consumption items, which are used to calculate
    variable drink costs.
    """
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
        """
        Calculates the total cost for this drink entry.

        Returns:
            Decimal: The total amount (quantity * unit_price).
        """
        return Decimal(self.quantity) * self.unit_price

    def __str__(self):
        """
        Returns a string representation of the Drink Entry.

        Returns:
            str: A descriptive string including the participant and drink type.
        """
        return f"{self.participant}: {self.get_drink_display()} x {self.quantity}"


class SettlementRun(TimeStampedModel):
    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="settlement_runs")
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_settlement_runs",
    )
    participant_count = models.PositiveIntegerField(default=0)
    total_gross = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_subsidy = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_due = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_advanced = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        timestamp = self.created_at.strftime("%d.%m.%Y %H:%M") if self.created_at else "ungespeichert"
        return f"Abrechnung {self.camp} vom {timestamp}"


class Settlement(TimeStampedModel):
    """
    Stores the final financial settlement calculation for a single Participant.

    The Settlement model is the source of truth for financial reconciliation.
    It aggregates all charges, payments, and expenses to determine the final
    balance owed or due back to the participant.
    """
    run = models.ForeignKey(SettlementRun, on_delete=models.CASCADE, related_name="settlements", null=True, blank=True)
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="settlements")
    calculated_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    total_gross = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_subsidy = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_due = models.DecimalField(max_digits=10, decimal_places=2)
    total_paid = models.DecimalField(max_digits=10, decimal_places=2)
    total_advanced = models.DecimalField(max_digits=10, decimal_places=2)
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ["run", "participant", "-created_at"]

    def __str__(self):
        """
        Returns a string representation of the Settlement.

        Returns:
            str: A descriptive string including the participant and the current balance.
        """
        return f"{self.participant}: {self.balance}"
