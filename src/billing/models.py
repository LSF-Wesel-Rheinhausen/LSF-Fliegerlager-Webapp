from datetime import time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UserProfile(TimeStampedModel):
    """Store editable application metadata for a Django user account."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=80, blank=True)

    def __str__(self):
        return f"Profil {self.user}"


class Camp(TimeStampedModel):
    name = models.CharField(max_length=160)
    year = models.PositiveIntegerField()
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    meal_booking_cutoff_time = models.TimeField(default=time(12, 0))
    shift_ratio_per_night = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Anzahl benötigter Dienste pro gebuchter Nacht, z.B. 0.2 für 1 Dienst pro 5 Nächte.",
    )
    iban = models.CharField(max_length=40, blank=True, help_text="IBAN für Überweisungen")
    paypal_link = models.CharField(max_length=200, blank=True, help_text="PayPal.me Link oder E-Mail-Adresse")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-year", "name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "year"], name="unique_camp_name_year"),
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="unique_active_camp",
            ),
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            camps = Camp.objects.select_for_update()
            if self._state.adding and not camps.exists():
                self.is_active = True
            if self.is_active:
                camps.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)
            elif (
                self.pk
                and camps.filter(pk=self.pk, is_active=True).exists()
                and not camps.exclude(pk=self.pk).filter(is_active=True).exists()
            ):
                raise ValidationError("Das einzige Lager kann nicht deaktiviert werden.")
            return super().save(*args, **kwargs)

    def validate_constraints(self, exclude: list[str] | None = None) -> None:
        """Exclude unique_active_camp from pre-save model validation since save() deactivates other camps."""
        if exclude is None:
            exclude = []
        exclude = list(exclude) + ["is_active"]
        super().validate_constraints(exclude=exclude)

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
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_participants",
    )

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

    @property
    def target_shifts(self) -> int:
        return int(round(Decimal(self.booked_nights) * self.camp.shift_ratio_per_night))

    @property
    def completed_shifts(self) -> int:
        if hasattr(self, "_completed_shifts_count"):
            return self._completed_shifts_count
        return self.shift_assignments.count()

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def __str__(self):
        return self.full_name


class ParticipantPin(TimeStampedModel):
    MAX_FAILED_ATTEMPTS = 5
    LOCK_MINUTES = 5

    participant = models.OneToOneField(Participant, on_delete=models.CASCADE, related_name="pin")
    pin_hash = models.CharField(max_length=256, blank=True)
    must_set_pin = models.BooleanField(default=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
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
        self.failed_attempts = 0
        self.locked_until = None
        self.changed_by = changed_by

    def reset_pin(self, changed_by=None):
        self.pin_hash = ""
        self.must_set_pin = True
        self.failed_attempts = 0
        self.locked_until = None
        self.changed_by = changed_by

    @property
    def is_locked(self):
        return self.locked_until is not None and self.locked_until > timezone.now()

    def check_pin(self, raw_pin):
        if not self.pin_hash or self.is_locked:
            return False
        if check_password(raw_pin, self.pin_hash):
            if self.failed_attempts or self.locked_until is not None:
                self.failed_attempts = 0
                self.locked_until = None
                self.save(update_fields=["failed_attempts", "locked_until", "updated_at"])
            return True

        self.failed_attempts += 1
        if self.failed_attempts >= self.MAX_FAILED_ATTEMPTS:
            self.locked_until = timezone.now() + timedelta(minutes=self.LOCK_MINUTES)
            self.failed_attempts = 0
        self.save(update_fields=["failed_attempts", "locked_until", "updated_at"])
        return False

    def __str__(self):
        return f"PIN {self.participant}"


class ParticipantFamilyMember(TimeStampedModel):
    """Represent a kiosk-only family member billed through a participant."""

    class Role(models.TextChoices):
        CHILD = "child", "Kind"
        COMPANION = "companion", "Begleitperson"

    guardian = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="family_members")
    first_name = models.CharField(max_length=120)
    last_name = models.CharField(max_length=120)
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    @property
    def full_name(self) -> str:
        """Return the display name used in kiosk booking dialogs."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_child(self) -> bool:
        """Return whether this family member should use child meal pricing."""
        return self.role == self.Role.CHILD

    def __str__(self):
        return f"{self.full_name} ({self.guardian})"


class ParticipantBookingLink(TimeStampedModel):
    """Track participant-to-participant kiosk booking invitations."""

    class Status(models.TextChoices):
        PENDING = "pending", "Offen"
        ACCEPTED = "accepted", "Angenommen"
        DECLINED = "declined", "Abgelehnt"
        REVOKED = "revoked", "Aufgelöst"

    inviter = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="sent_booking_links")
    invitee = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="received_booking_links")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(inviter=models.F("invitee")),
                name="booking_link_distinct_participants",
            ),
        ]

    def __str__(self):
        return f"{self.inviter} -> {self.invitee} ({self.get_status_display()})"


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
    foerdersatz = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
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
    foerdersatz = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
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
        if self._state.adding:
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
    """Store one kiosk meal booking or retraction for a person and meal slot."""

    class Meal(models.TextChoices):
        BREAKFAST = "breakfast", "Frühstück"
        DINNER = "dinner", "Abendessen"

    class Status(models.TextChoices):
        ACTIVE = "active", "Gebucht"
        RETRACTED = "retracted", "Zurückgenommen"

    class Variant(models.TextChoices):
        NORMAL = "normal", "Mit Fleisch"
        VEGAN = "vegan", "Vegan"
        NORMAL_CHILD = "normal_child", "Mit Fleisch Kind"
        VEGAN_CHILD = "vegan_child", "Vegan Kind"

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="meal_signups")
    family_member = models.ForeignKey(
        ParticipantFamilyMember,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="meal_signups",
    )
    meal_date = models.DateField()
    meal = models.CharField(max_length=20, choices=Meal.choices)
    variant = models.CharField(max_length=20, choices=Variant.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    foerdersatz = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    retracted_at = models.DateTimeField(null=True, blank=True)
    charge = models.ForeignKey(
        Charge,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meal_signups",
    )

    class Meta:
        ordering = ["meal_date", "meal", "participant"]
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "meal_date", "meal"],
                condition=models.Q(family_member__isnull=True),
                name="unique_meal_signup",
            ),
            models.UniqueConstraint(
                fields=["participant", "family_member", "meal_date", "meal"],
                condition=models.Q(family_member__isnull=False),
                name="unique_family_member_meal_signup",
            ),
        ]

    def __str__(self):
        return f"{self.participant}: {self.meal_date} {self.meal}"


class MealOrder(TimeStampedModel):
    """Track that the catering meal order for one camp day has been sent."""

    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="meal_orders")
    meal_date = models.DateField()
    ordered_at = models.DateTimeField(default=timezone.now)
    ordered_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_meal_orders",
    )

    class Meta:
        ordering = ["-meal_date"]
        constraints = [
            models.UniqueConstraint(fields=["camp", "meal_date"], name="unique_meal_order_per_camp_date"),
        ]

    def __str__(self):
        return f"{self.camp}: Bestellung {self.meal_date}"


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
    foerdersatz = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    booked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-booked_at", "participant"]

    @property
    def total(self):
        return Decimal(self.quantity) * self.unit_price

    def __str__(self):
        return f"{self.participant}: {self.get_drink_display()} x {self.quantity}"


class SettlementRun(TimeStampedModel):
    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="settlement_runs")
    version = models.PositiveIntegerField()
    calculated_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calculated_settlement_runs",
    )
    participant_count = models.PositiveIntegerField(default=0)
    total_gross = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total_subsidy = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total_due = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total_advanced = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["camp", "version"], name="unique_settlement_run_version")]

    def __str__(self):
        return f"{self.camp}: Abrechnung V{self.version}"


class Settlement(TimeStampedModel):
    run = models.ForeignKey(
        SettlementRun,
        on_delete=models.CASCADE,
        related_name="settlements",
        null=True,
        blank=True,
    )
    participant = models.ForeignKey(Participant, on_delete=models.RESTRICT, related_name="settlements")
    calculated_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    participant_name = models.CharField(max_length=250, blank=True)
    participant_status = models.CharField(max_length=20, blank=True)
    total_gross = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    total_subsidy = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    total_due = models.DecimalField(max_digits=10, decimal_places=2)
    total_paid = models.DecimalField(max_digits=10, decimal_places=2)
    total_advanced = models.DecimalField(max_digits=10, decimal_places=2)
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ["participant", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "participant"],
                condition=models.Q(run__isnull=False),
                name="unique_participant_per_settlement_run",
            )
        ]

    def __str__(self):
        return f"{self.participant}: {self.balance}"


class Shift(TimeStampedModel):
    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="shifts")
    name = models.CharField(max_length=120)
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    required_slots = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["date", "start_time", "name"]

    @property
    def is_full(self) -> bool:
        if hasattr(self, "assignments_count"):
            return self.assignments_count >= self.required_slots
        return self.assignments.count() >= self.required_slots

    def __str__(self):
        return f"{self.camp}: {self.date} {self.name}"


class DailyShiftTemplate(TimeStampedModel):
    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="daily_shift_templates")
    name = models.CharField(max_length=120)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    required_slots = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["start_time", "name"]

    def __str__(self):
        return f"{self.camp}: Täglich {self.name}"


class DailyShiftException(TimeStampedModel):
    template = models.ForeignKey(DailyShiftTemplate, on_delete=models.CASCADE, related_name="exceptions")
    date = models.DateField()
    is_skipped = models.BooleanField(default=False)
    custom_required_slots = models.PositiveIntegerField(null=True, blank=True)
    custom_start_time = models.TimeField(null=True, blank=True)
    custom_end_time = models.TimeField(null=True, blank=True)

    class Meta:
        ordering = ["date", "template"]
        constraints = [models.UniqueConstraint(fields=["template", "date"], name="unique_shift_exception")]

    def __str__(self):
        return f"Ausnahme am {self.date} für {self.template.name}"


class ShiftAssignment(TimeStampedModel):
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name="assignments")
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="shift_assignments")
    offered_for_exchange = models.BooleanField(default=False)

    class Meta:
        ordering = ["shift", "participant"]
        constraints = [
            models.UniqueConstraint(fields=["shift", "participant"], name="unique_shift_assignment"),
        ]

    def __str__(self):
        return f"{self.participant} -> {self.shift}"
