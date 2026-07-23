from collections.abc import Collection
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


class EmailConfiguration(TimeStampedModel):
    """Store the singleton SMTP configuration managed by administrators."""

    class Security(models.TextChoices):
        STARTTLS = "starttls", "STARTTLS"
        SSL = "ssl", "SSL/TLS"

    enabled = models.BooleanField(default=False)
    host = models.CharField(max_length=255, blank=True)
    port = models.PositiveIntegerField(default=587)
    username = models.CharField(max_length=254, blank=True)
    password_encrypted = models.TextField(blank=True)
    security = models.CharField(max_length=20, choices=Security.choices, default=Security.STARTTLS)
    from_name = models.CharField(max_length=160, blank=True)
    from_email = models.EmailField(blank=True)
    reply_to = models.EmailField(blank=True)
    timeout = models.PositiveSmallIntegerField(default=10)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_email_configurations",
    )
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_tested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tested_email_configurations",
    )

    class Meta:
        verbose_name = "E-Mail-Konfiguration"
        verbose_name_plural = "E-Mail-Konfigurationen"

    @classmethod
    def load(cls) -> "EmailConfiguration":
        configuration, _created = cls.objects.get_or_create(pk=1)
        return configuration

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)

    def set_password(self, password: str) -> None:
        """Replace the encrypted SMTP password."""
        from .email_credentials import encrypt_email_password

        self.password_encrypted = encrypt_email_password(password)

    def get_password(self) -> str:
        """Return the decrypted SMTP password."""
        from .email_credentials import decrypt_email_password

        return decrypt_email_password(self.password_encrypted)

    def __str__(self) -> str:
        return self.from_email or "E-Mail-Versand"


class EmailTestLog(TimeStampedModel):
    """Audit one explicit SMTP test without storing credentials or response text."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Erfolgreich"
        FAILED = "failed", "Fehlgeschlagen"

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="email_test_logs",
    )
    recipient_email = models.EmailField()
    status = models.CharField(max_length=20, choices=Status.choices)
    error_code = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.get_status_display()}: {self.created_at}"


class EmailBatch(TimeStampedModel):
    """Record one manually confirmed information or invoice delivery batch."""

    class Kind(models.TextChoices):
        INFORMATION = "information", "Information"
        SETTLEMENT = "settlement", "Rechnung"

    camp = models.ForeignKey("Camp", on_delete=models.RESTRICT, related_name="email_batches")
    settlement_run = models.ForeignKey(
        "SettlementRun",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="email_batches",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    subject = models.CharField(max_length=160)
    body = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_email_batches",
    )

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind="information", settlement_run__isnull=True)
                    | models.Q(kind="settlement", settlement_run__isnull=False)
                ),
                name="email_batch_run_matches_kind",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.subject}"


class EmailDelivery(TimeStampedModel):
    """Store one recipient-specific delivery attempt in the manual email outbox."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ausstehend"
        PROCESSING = "processing", "In Verarbeitung"
        SENT = "sent", "Gesendet"
        FAILED = "failed", "Fehlgeschlagen"

    batch = models.ForeignKey(EmailBatch, on_delete=models.CASCADE, related_name="deliveries")
    settlement = models.ForeignKey(
        "Settlement",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="email_deliveries",
    )
    recipient_email = models.EmailField()
    recipient_names = models.JSONField(default=list)
    dedupe_key = models.CharField(max_length=180)
    subject = models.CharField(max_length=160)
    body_text = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=40, blank=True)
    attachment_filename = models.CharField(max_length=255, blank=True)
    attachment_content = models.BinaryField(null=True, blank=True, editable=False)
    attachment_sha256 = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "dedupe_key"], name="unique_email_delivery_dedupe"),
            models.UniqueConstraint(
                fields=["settlement"],
                condition=models.Q(
                    settlement__isnull=False,
                    status__in=["pending", "processing"],
                ),
                name="unique_active_settlement_email_delivery",
            ),
        ]
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="email_delivery_due_idx")]

    def __str__(self) -> str:
        return f"E-Mail-Zustellung {self.pk} ({self.get_status_display()})"


class UserProfile(TimeStampedModel):
    """Store editable application metadata for a Django user account."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=80, blank=True)

    def __str__(self):
        return f"Profil {self.user}"


class PasskeyCredential(TimeStampedModel):
    """Store a verified WebAuthn credential for an application user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="passkey_credentials",
    )
    name = models.CharField(max_length=120)
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveBigIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)
    device_type = models.CharField(max_length=32, blank=True)
    backed_up = models.BooleanField(default=False)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name", "created_at"]

    @property
    def user_handle(self) -> bytes:
        """Return the stable, non-PII WebAuthn user handle for this account."""
        return self.user_id.to_bytes(8, byteorder="big", signed=False)

    def __str__(self) -> str:
        return f"{self.name} ({self.user})"


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

    def validate_constraints(self, exclude: Collection[str] | None = None) -> None:
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
    arrival_date = models.DateField(null=True, blank=True)
    departure_date = models.DateField(null=True, blank=True)
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

    def save(self, *args, **kwargs):
        if self.arrival_date and self.departure_date:
            days = (self.departure_date - self.arrival_date).days
            if days > 0:
                self.booked_nights = days
        super().save(*args, **kwargs)

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
    arrival_date = models.DateField(null=True, blank=True)
    departure_date = models.DateField(null=True, blank=True)
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


class ParticipantFamilyMemberPin(TimeStampedModel):
    """Store the kiosk PIN for a companion family member."""

    MAX_FAILED_ATTEMPTS = 5
    LOCK_MINUTES = 5

    family_member = models.OneToOneField(ParticipantFamilyMember, on_delete=models.CASCADE, related_name="pin")
    pin_hash = models.CharField(max_length=256, blank=True)
    must_set_pin = models.BooleanField(default=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    def set_pin(self, raw_pin: str) -> None:
        """Persist a hashed kiosk PIN for this companion."""
        self.pin_hash = make_password(raw_pin)
        self.must_set_pin = False
        self.failed_attempts = 0
        self.locked_until = None

    def reset_pin(self) -> None:
        """Force the companion to choose a new kiosk PIN."""
        self.pin_hash = ""
        self.must_set_pin = True
        self.failed_attempts = 0
        self.locked_until = None

    @property
    def is_locked(self) -> bool:
        """Return whether failed PIN attempts temporarily block login."""
        return self.locked_until is not None and self.locked_until > timezone.now()

    def check_pin(self, raw_pin: str) -> bool:
        """Validate a raw PIN and apply lockout accounting."""
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
        return f"PIN {self.family_member}"


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
        SNACK = "snack", "Mittagssnack"

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
    is_archived = models.BooleanField(default=False)

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
    kiosk_booked_by = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kiosk_created_charges",
        help_text="Teilnehmer, der diese Kiosk-Schnellbuchung ausgelöst hat.",
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
    class Status(models.TextChoices):
        PENDING = "pending", "Ausstehend"
        APPROVED = "approved", "Genehmigt"
        REJECTED = "rejected", "Abgelehnt"

    class AllocationMethod(models.TextChoices):
        NONE = "none", "Nicht umlegen"
        COST_CENTER = "cost_center", "Auf Kostenstelle umlegen"
        ALL_ACTIVE = "all_active", "Alle aktiven Teilnehmer"
        SELECTED = "selected", "Ausgewählte Teilnehmer"

    class CostCenter(models.TextChoices):
        FOOD_BREAKFAST = "food_breakfast", "Unterkunft/Verpflegung - Frühstück"
        FOOD_DINNER = "food_dinner", "Unterkunft/Verpflegung - Abendessen"
        FOOD_OTHER = "food_other", "Unterkunft/Verpflegung - Sonstiges"
        TRAVEL = "travel", "Fahrtkosten"
        MATERIALS = "materials", "Verbrauchsmaterial"
        RENT_OTHER = "rent_other", "Miete/sonstiges"

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
    receipt = models.FileField(upload_to="receipts/", blank=True, null=True, verbose_name="Rechnungsbeleg")
    paid_on = models.DateField(null=True, blank=True)
    reimbursable = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.TextField(blank=True, help_text="Begründung der Ablehnung, sichtbar für den Teilnehmer.")
    allocation_method = models.CharField(max_length=20, choices=AllocationMethod.choices, default=AllocationMethod.NONE)
    cost_center = models.CharField(max_length=50, choices=CostCenter.choices, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_expenses",
    )

    class Meta:
        ordering = ["category", "description"]

    def __str__(self):
        return f"{self.camp}: {self.description}"


class ExpenseAllocation(TimeStampedModel):
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="allocations")
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="expense_allocations")
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["expense", "participant"]
        constraints = [
            models.UniqueConstraint(fields=["expense", "participant"], name="unique_expense_allocation"),
        ]

    def __str__(self):
        return f"{self.participant} -> {self.expense}: {self.amount}"


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


class MealPlanEntry(TimeStampedModel):
    """Store the visible menu description for one camp meal slot."""

    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="meal_plan_entries")
    meal_date = models.DateField()
    meal = models.CharField(max_length=20, choices=MealSignup.Meal.choices)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["meal_date", "meal"]
        constraints = [
            models.UniqueConstraint(fields=["camp", "meal_date", "meal"], name="unique_meal_plan_entry"),
        ]

    def __str__(self):
        return f"{self.camp}: {self.get_meal_display()} {self.meal_date}"


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
    class RunType(models.TextChoices):
        MANUAL = "manual", "Manuell"
        DAILY_BACKUP = "daily_backup", "Tägliches Backup"

    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="settlement_runs")
    version = models.PositiveIntegerField()
    run_type = models.CharField(max_length=20, choices=RunType.choices, default=RunType.MANUAL)
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
    cost_center_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["camp", "version"], name="unique_settlement_run_version")]

    def __str__(self):
        return f"{self.camp}: Abrechnung V{self.version}"


class DailySettlementBackupSettings(TimeStampedModel):
    """Store the singleton schedule for automated settlement backup runs."""

    enabled = models.BooleanField(default=False)
    run_time = models.TimeField(default=time(5, 0))

    class Meta:
        verbose_name = "Tägliche Abrechnungs-Backup-Einstellung"
        verbose_name_plural = "Tägliche Abrechnungs-Backup-Einstellungen"

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        settings, _created = cls.objects.get_or_create(pk=1)
        return settings

    def __str__(self):
        status = "aktiv" if self.enabled else "inaktiv"
        return f"Tägliche Abrechnungs-Backups {status} um {self.run_time:%H:%M}"


class DailySettlementBackupLog(TimeStampedModel):
    """Record one attempted automated settlement backup for a camp and date."""

    class Status(models.TextChoices):
        RUNNING = "running", "Läuft"
        SUCCESS = "success", "Erfolgreich"
        FAILED = "failed", "Fehlgeschlagen"
        SKIPPED = "skipped", "Übersprungen"

    camp = models.ForeignKey(Camp, on_delete=models.SET_NULL, null=True, blank=True, related_name="daily_backup_logs")
    run_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    settlement_run = models.ForeignKey(
        SettlementRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_backup_logs",
    )
    backup_file = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-run_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["camp", "run_date"],
                condition=models.Q(camp__isnull=False),
                name="unique_daily_settlement_backup_per_camp_date",
            ),
            models.UniqueConstraint(
                fields=["run_date"],
                condition=models.Q(camp__isnull=True),
                name="unique_daily_settlement_backup_no_camp_date",
            ),
        ]

    def __str__(self):
        camp_name = str(self.camp) if self.camp else "Kein aktives Lager"
        return f"{camp_name}: {self.run_date} {self.get_status_display()}"


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


class PushSubscription(TimeStampedModel):
    """Store one browser push capability for an admin or participant device."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        null=True,
        blank=True,
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        null=True,
        blank=True,
    )
    endpoint = models.URLField(max_length=2048, unique=True)  # noqa: DJ001
    p256dh = models.CharField(max_length=512)
    auth = models.CharField(max_length=512)
    device_name = models.CharField(max_length=80, default="Dieses Gerät")
    categories = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    failure_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["device_name", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, participant__isnull=True)
                    | models.Q(user__isnull=True, participant__isnull=False)
                ),
                name="push_subscription_exactly_one_owner",
            )
        ]

    def __str__(self) -> str:
        owner = self.user_id or self.participant_id
        return f"Push-Gerät {self.device_name} ({owner})"


class PushMessage(TimeStampedModel):
    """Store a reliable, idempotent push-delivery attempt in the database outbox."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ausstehend"
        SENT = "sent", "Gesendet"
        FAILED = "failed", "Fehlgeschlagen"

    subscription = models.ForeignKey(PushSubscription, on_delete=models.CASCADE, related_name="messages")
    category = models.CharField(max_length=40)
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=300)
    target_url = models.CharField(max_length=500)
    dedupe_key = models.CharField(max_length=180)
    scheduled_for = models.DateTimeField(default=timezone.now)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["scheduled_for", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["subscription", "dedupe_key"], name="unique_push_message_dedupe"),
        ]
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="push_due_idx")]

    def __str__(self) -> str:
        return f"{self.category}: {self.title}"
