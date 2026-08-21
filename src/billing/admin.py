from django.contrib import admin
from django.contrib.admin.widgets import AdminDateWidget, AdminSplitDateTime
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.db import models, transaction
from django.utils import timezone

from .forms import ExpenseAdminForm
from .models import (
    BookingAuditLog,
    Camp,
    Charge,
    DailySettlementBackupLog,
    DailySettlementBackupSettings,
    DailyShiftException,
    DailyShiftTemplate,
    DrinkEntry,
    Expense,
    KioskActionAuditLog,
    MealBookingOverride,
    MealOrder,
    MealPlanEntry,
    MealSignup,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    Payment,
    PaymentAuditLog,
    PriceRule,
    Settlement,
    SettlementRun,
    Shift,
    ShiftAssignment,
    UserProfile,
)
from .services import (
    charge_audit_snapshot,
    create_booking_delete_audit_log,
    create_payment_delete_audit_log,
    generate_shifts_from_templates,
    payment_audit_snapshot,
    restore_booking_from_audit_log,
    restore_payment_from_audit_log,
)

admin.site.unregister(User)


def _without_timezone_warning_reference(value: str | None, name: str) -> str | None:
    """Remove only the admin-generated warning reference for one field."""
    if not value:
        return None
    warning_reference = f"id_{name}_timezone_warning_helptext"
    references = [reference for reference in value.split() if reference != warning_reference]
    return " ".join(references) or None


class AccessibleAdminDateWidget(AdminDateWidget):
    """Keep admin date controls free of absent timezone warning references."""

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        describedby = (attrs or {}).get("aria-describedby") or context["widget"]["attrs"].get("aria-describedby")
        filtered_describedby = _without_timezone_warning_reference(describedby, name)
        if filtered_describedby is None:
            context["widget"]["attrs"].pop("aria-describedby", None)
        else:
            context["widget"]["attrs"]["aria-describedby"] = filtered_describedby
        return context


class AccessibleAdminSplitDateTime(AdminSplitDateTime):
    """Keep both admin datetime subinputs free of absent warning references."""

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        describedby = (attrs or {}).get("aria-describedby") or self.attrs.get("aria-describedby")
        for subwidget in context["widget"]["subwidgets"]:
            filtered_describedby = _without_timezone_warning_reference(
                describedby or subwidget["attrs"].get("aria-describedby"), name
            )
            if filtered_describedby is None:
                subwidget["attrs"].pop("aria-describedby", None)
            else:
                subwidget["attrs"]["aria-describedby"] = filtered_describedby
        return context


@admin.register(User)
class ProtectedUserAdmin(UserAdmin):
    """Keep Django privilege fields exclusive to existing superusers."""

    protected_fields = frozenset({"is_staff", "is_superuser", "groups", "user_permissions"})

    def get_fieldsets(self, request, obj=None):
        """Hide privilege-bearing fields from delegated user administrators."""
        fieldsets = super().get_fieldsets(request, obj)
        if request.user.is_superuser:
            return fieldsets
        return tuple(
            (
                name,
                {
                    **options,
                    "fields": tuple(field for field in options.get("fields", ()) if field not in self.protected_fields),
                },
            )
            for name, options in fieldsets
        )

    def has_change_permission(self, request, obj=None):
        """Prevent delegated administrators from taking over superuser accounts."""
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        """Prevent delegated administrators from deleting superuser accounts."""
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Camp)
class CampAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "meal_booking_cutoff_time", "is_active", "starts_on", "ends_on")
    search_fields = ("name",)


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "camp", "status", "hilfssatz", "berufssatz", "actual_nights", "is_child")
    list_filter = ("camp", "status", "is_child", "is_youth_group", "is_companion")
    search_fields = ("first_name", "last_name", "email")
    formfield_overrides = {
        models.DateField: {"widget": AccessibleAdminDateWidget},
        models.DateTimeField: {"widget": AccessibleAdminSplitDateTime},
    }

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(UserProfile)


@admin.register(ParticipantFamilyMember)
class ParticipantFamilyMemberAdmin(admin.ModelAdmin):
    settlement_fields = ("role", "is_youth_group", "arrival_date", "departure_date", "is_active")
    list_display = ("last_name", "first_name", "guardian", "role", "is_active")
    list_filter = ("role", "is_active", "guardian__camp")
    search_fields = ("first_name", "last_name", "guardian__first_name", "guardian__last_name")

    def get_readonly_fields(self, request, obj=None):
        """Require settlement-relevant edits to use the confirmed participant workflow."""
        if obj is not None:
            return self.settlement_fields
        return ()


@admin.register(ParticipantBookingLink)
class ParticipantBookingLinkAdmin(admin.ModelAdmin):
    """Expose participant consent records without allowing administrative writes."""

    list_display = ("inviter", "invitee", "status", "created_at", "updated_at")
    list_filter = ("status", "created_at")
    search_fields = ("inviter__first_name", "inviter__last_name", "invitee__first_name", "invitee__last_name")

    def has_add_permission(self, request):
        """Require creation through the audited participant invitation workflow."""
        return False

    def has_change_permission(self, request, obj=None):
        """Require status changes through the audited participant consent workflow."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Retain participant consent history for authorization audits."""
        return False


@admin.register(PriceRule)
class PriceRuleAdmin(admin.ModelAdmin):
    list_display = (
        "camp",
        "kind",
        "name",
        "unit_price",
        "camp_flat_duration",
        "camp_flat_role",
        "foerdersatz",
        "is_default",
    )
    list_filter = ("camp", "kind", "camp_flat_duration", "camp_flat_role", "is_default")


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    list_display = (
        "booking_reference",
        "participant",
        "family_member",
        "kind",
        "description",
        "unit_price",
        "foerdersatz",
        "occurred_on",
        "deleted_at",
    )
    list_filter = ("kind", "deleted_at", "family_member__role")
    search_fields = (
        "id",
        "description",
        "participant__first_name",
        "participant__last_name",
        "family_member__first_name",
        "family_member__last_name",
    )
    readonly_fields = ("deleted_at", "deleted_by")
    actions = ["soft_delete_selected_charges", "restore_selected_charges"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("participant", "family_member")

    @admin.display(description="Buchungsnr.", ordering="id")
    def booking_reference(self, charge: Charge) -> str:
        """Return the formatted booking reference for the admin changelist."""
        return charge.booking_reference

    @admin.action(description="Ausgewählte Buchungen als gelöscht markieren (Soft-Delete)")
    def soft_delete_selected_charges(self, request, queryset):
        active_charges = list(queryset.filter(deleted_at__isnull=True))
        if not active_charges:
            self.message_user(request, "Keine aktiven Buchungen zum Löschen ausgewählt.", level="warning")
            return
        now = timezone.now()
        with transaction.atomic():
            for charge in active_charges:
                before = charge_audit_snapshot(charge)
                create_booking_delete_audit_log(charge, before, request.user)
                charge.deleted_at = now
                charge.deleted_by = request.user
                charge.save(update_fields=["deleted_at", "deleted_by"])
        self.message_user(request, f"{len(active_charges)} Buchung(en) wurden als gelöscht markiert.")

    @admin.action(description="Ausgewählte gelöschte Buchungen wiederherstellen")
    def restore_selected_charges(self, request, queryset):
        deleted_charges = list(queryset.filter(deleted_at__isnull=False))
        if not deleted_charges:
            self.message_user(request, "Keine gelöschten Buchungen zur Wiederherstellung ausgewählt.", level="warning")
            return
        restored_count = 0
        with transaction.atomic():
            for charge in deleted_charges:
                audit_log = (
                    BookingAuditLog.objects.filter(charge=charge, action=BookingAuditLog.Action.DELETED)
                    .order_by("-created_at")
                    .first()
                )
                if audit_log:
                    try:
                        restore_booking_from_audit_log(audit_log, request.user)
                        restored_count += 1
                    except Exception:
                        continue
                else:
                    before = charge_audit_snapshot(charge)
                    charge.deleted_at = None
                    charge.deleted_by = None
                    charge.save(update_fields=["deleted_at", "deleted_by"])
                    BookingAuditLog.objects.create(
                        participant=charge.participant,
                        charge=charge,
                        changed_by=request.user,
                        action=BookingAuditLog.Action.RESTORED,
                        before=before,
                        after=charge_audit_snapshot(charge),
                    )
                    restored_count += 1
        self.message_user(request, f"{restored_count} Buchung(en) wurden wiederhergestellt.")


@admin.register(BookingAuditLog)
class BookingAuditLogAdmin(admin.ModelAdmin):
    list_display = ("participant", "charge", "action", "changed_by", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("charge__description", "participant__first_name", "participant__last_name")
    readonly_fields = ("participant", "charge", "action", "changed_by", "before", "after", "created_at")
    actions = ["restore_charges_from_audit_log"]

    @admin.action(description="Ausgewählte Buchungen aus Audit-Protokoll wiederherstellen")
    def restore_charges_from_audit_log(self, request, queryset):
        deletion_logs = list(queryset.filter(action=BookingAuditLog.Action.DELETED))
        if not deletion_logs:
            self.message_user(request, "Keine Löschungs-Protokolleinträge ausgewählt.", level="warning")
            return
        restored_count = 0
        with transaction.atomic():
            for log in deletion_logs:
                if log.charge and log.charge.deleted_at is not None:
                    try:
                        restore_booking_from_audit_log(log, request.user)
                        restored_count += 1
                    except Exception:
                        continue
        self.message_user(request, f"{restored_count} Buchung(en) wurden aus dem Audit-Protokoll wiederhergestellt.")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("payment_reference", "participant", "amount", "paid_on", "method", "deleted_at")
    list_filter = ("deleted_at", "method")
    search_fields = ("id", "note", "participant__first_name", "participant__last_name")
    readonly_fields = ("deleted_at", "deleted_by")
    actions = ["soft_delete_selected_payments", "restore_selected_payments"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("participant")

    def has_delete_permission(self, request, obj=None):
        """Disable hard deletes so payments remain auditable via soft-delete."""
        return False
    @admin.display(description="Zahlungsnr.", ordering="id")
    def payment_reference(self, payment: Payment) -> str:
        """Return the formatted payment reference for the admin changelist."""
        return payment.payment_reference

    @admin.action(description="Ausgewählte Zahlungen als gelöscht markieren (Soft-Delete)")
    def soft_delete_selected_payments(self, request, queryset):
        active_payments = list(queryset.filter(deleted_at__isnull=True))
        if not active_payments:
            self.message_user(request, "Keine aktiven Zahlungen zum Löschen ausgewählt.", level="warning")
            return
        now = timezone.now()
        with transaction.atomic():
            for payment in active_payments:
                before = payment_audit_snapshot(payment)
                create_payment_delete_audit_log(payment, before, request.user)
                payment.deleted_at = now
                payment.deleted_by = request.user
                payment.save(update_fields=["deleted_at", "deleted_by"])
        self.message_user(request, f"{len(active_payments)} Zahlung(en) wurden als gelöscht markiert.")

    @admin.action(description="Ausgewählte gelöschte Zahlungen wiederherstellen")
    def restore_selected_payments(self, request, queryset):
        deleted_payments = list(queryset.filter(deleted_at__isnull=False))
        if not deleted_payments:
            self.message_user(request, "Keine gelöschten Zahlungen zur Wiederherstellung ausgewählt.", level="warning")
            return
        restored_count = 0
        with transaction.atomic():
            for payment in deleted_payments:
                audit_log = (
                    PaymentAuditLog.objects.filter(payment=payment, action=PaymentAuditLog.Action.DELETED)
                    .order_by("-created_at")
                    .first()
                )
                if audit_log is None:
                    continue
    @admin.action(description="Ausgewählte gelöschte Zahlungen wiederherstellen")
    def restore_selected_payments(self, request, queryset):
        from django.core.exceptions import ValidationError

        deleted_payments = list(queryset.filter(deleted_at__isnull=False))
        if not deleted_payments:
            self.message_user(request, "Keine gelöschten Zahlungen zur Wiederherstellung ausgewählt.", level="warning")
            return
        restored_count = 0
        with transaction.atomic():
            for payment in deleted_payments:
                audit_log = (
                    PaymentAuditLog.objects.filter(payment=payment, action=PaymentAuditLog.Action.DELETED)
                    .order_by("-created_at")
                    .first()
                )
                if audit_log is None:
                    continue
                try:
                    restore_payment_from_audit_log(audit_log, request.user)
                except ValidationError:
                    continue
                restored_count += 1
        self.message_user(request, f"{restored_count} Zahlung(en) wurden wiederhergestellt.")


@admin.register(PaymentAuditLog)
class PaymentAuditLogAdmin(admin.ModelAdmin):
    list_display = ("participant", "payment", "action", "changed_by", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("participant__first_name", "participant__last_name")
    readonly_fields = ("participant", "payment", "action", "changed_by", "before", "after", "created_at")
    actions = ["restore_payments_from_audit_log"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Ausgewählte Zahlungen aus Audit-Protokoll wiederherstellen")
    def restore_payments_from_audit_log(self, request, queryset):
        deletion_logs = list(queryset.filter(action=PaymentAuditLog.Action.DELETED))
        if not deletion_logs:
            self.message_user(request, "Keine Löschungs-Protokolleinträge ausgewählt.", level="warning")
            return
        restored_count = 0
        with transaction.atomic():
            for log in deletion_logs:
                if log.payment is None or log.payment.deleted_at is None:
                    continue
                try:
                    restore_payment_from_audit_log(log, request.user)
                except Exception:
                    continue
                restored_count += 1
        self.message_user(request, f"{restored_count} Zahlung(en) wurden aus dem Audit-Protokoll wiederhergestellt.")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    form = ExpenseAdminForm


admin.site.register(DailySettlementBackupSettings)


@admin.register(DailySettlementBackupLog)
class DailySettlementBackupLogAdmin(admin.ModelAdmin):
    list_display = ("run_date", "camp", "status", "settlement_run", "backup_file", "finished_at")
    list_filter = ("status", "run_date")
    search_fields = ("backup_file", "error", "camp__name")
    readonly_fields = (
        "camp",
        "run_date",
        "status",
        "settlement_run",
        "backup_file",
        "error",
        "started_at",
        "finished_at",
    )


@admin.register(MealSignup)
class MealSignupAdmin(admin.ModelAdmin):
    list_display = ("participant", "family_member", "meal_date", "meal", "variant", "status", "retracted_at")
    list_filter = ("participant__camp", "meal", "variant", "status", "meal_date")
    search_fields = (
        "participant__first_name",
        "participant__last_name",
        "family_member__first_name",
        "family_member__last_name",
    )


@admin.register(MealOrder)
class MealOrderAdmin(admin.ModelAdmin):
    """Expose catering-order markers without bypassing the serialized application workflow."""

    list_display = ("camp", "meal_date", "is_sent", "ordered_at", "ordered_by", "unmarked_at", "unmarked_by")
    list_filter = ("camp", "meal_date", "ordered_at")
    search_fields = ("camp__name", "ordered_by__username", "ordered_by__email")

    def has_add_permission(self, request):
        """Require the meal overview for creating sent markers."""
        return False

    def has_change_permission(self, request, obj=None):
        """Keep the raw Django admin as a read-only audit view."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Require the meal overview for reversing sent markers."""
        return False


@admin.register(MealBookingOverride)
class MealBookingOverrideAdmin(admin.ModelAdmin):
    """Expose current meal booking overrides as read-only records."""

    list_display = ("camp", "meal_date", "meal", "state", "changed_at", "changed_by")
    list_filter = ("camp", "meal", "state", "meal_date")
    search_fields = ("camp__name", "changed_by__username", "changed_by__email")

    def has_add_permission(self, request):
        """Require the application calendar for creating overrides."""
        return False

    def has_change_permission(self, request, obj=None):
        """Keep the raw Django admin as a read-only audit view."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Require the application calendar for changing the current state."""
        return False


@admin.register(MealPlanEntry)
class MealPlanEntryAdmin(admin.ModelAdmin):
    list_display = ("camp", "meal_date", "meal", "description")
    list_filter = ("camp", "meal", "meal_date")
    search_fields = ("camp__name", "description")


admin.site.register(DrinkEntry)


class ReadOnlySnapshotAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(KioskActionAuditLog)
class KioskActionAuditLogAdmin(ReadOnlySnapshotAdmin):
    list_display = (
        "camp",
        "actor_participant",
        "actor_display_name",
        "target_participant",
        "target_display_name",
        "action",
        "created_at",
    )
    list_filter = ("camp", "action", "created_at")
    search_fields = (
        "actor_participant__first_name",
        "actor_participant__last_name",
        "target_participant__first_name",
        "target_participant__last_name",
        "actor_display_name_snapshot",
        "target_display_name_snapshot",
        "description",
    )
    readonly_fields = (
        "camp",
        "actor_participant",
        "actor_family_member",
        "actor_display_name_snapshot",
        "target_participant",
        "target_family_member",
        "target_display_name_snapshot",
        "booking_link",
        "charge",
        "action",
        "description",
        "before",
        "after",
        "created_at",
    )


@admin.register(SettlementRun)
class SettlementRunAdmin(ReadOnlySnapshotAdmin):
    list_display = ("camp", "version", "created_at", "calculated_by", "participant_count", "balance")
    list_filter = ("camp", "created_at")


@admin.register(Settlement)
class SettlementAdmin(ReadOnlySnapshotAdmin):
    list_display = ("participant_name", "run", "total_due", "balance", "created_at")
    list_filter = ("run__camp", "run__version")


class DailyShiftExceptionInline(admin.TabularInline):
    model = DailyShiftException
    extra = 1


@admin.register(DailyShiftTemplate)
class DailyShiftTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "camp", "start_time", "end_time", "required_slots")
    list_filter = ("camp",)
    inlines = [DailyShiftExceptionInline]
    actions = ["generate_shifts_for_templates"]

    @admin.action(description="Dienste für ausgewählte Vorlagen generieren")
    def generate_shifts_for_templates(self, request, queryset):
        generated_count, skipped_count = generate_shifts_from_templates(queryset)
        self.message_user(
            request, f"{generated_count} Dienste generiert, {skipped_count} wegen Ausnahmen übersprungen."
        )


class ShiftAssignmentInline(admin.TabularInline):
    model = ShiftAssignment
    extra = 0


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("name", "camp", "date", "start_time", "end_time", "required_slots", "is_full")
    list_filter = ("camp", "date")
    inlines = [ShiftAssignmentInline]
