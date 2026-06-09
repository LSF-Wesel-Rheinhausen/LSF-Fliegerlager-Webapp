from django.contrib import admin

from .models import (
    BookingAuditLog,
    Camp,
    Charge,
    DailyShiftException,
    DailyShiftTemplate,
    DrinkEntry,
    Expense,
    MealOrder,
    MealSignup,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    ParticipantPin,
    Payment,
    PriceRule,
    Settlement,
    SettlementRun,
    Shift,
    ShiftAssignment,
    UserProfile,
)


@admin.register(Camp)
class CampAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "meal_booking_cutoff_time", "is_active", "starts_on", "ends_on")
    search_fields = ("name",)


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "camp", "status", "hilfssatz", "berufssatz", "actual_nights", "is_child")
    list_filter = ("camp", "status", "is_child", "is_youth_group", "is_companion")
    search_fields = ("first_name", "last_name", "email")

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(ParticipantPin)
admin.site.register(UserProfile)


@admin.register(ParticipantFamilyMember)
class ParticipantFamilyMemberAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "guardian", "role", "is_active")
    list_filter = ("role", "is_active", "guardian__camp")
    search_fields = ("first_name", "last_name", "guardian__first_name", "guardian__last_name")


@admin.register(ParticipantBookingLink)
class ParticipantBookingLinkAdmin(admin.ModelAdmin):
    list_display = ("inviter", "invitee", "status", "created_at", "updated_at")
    list_filter = ("status", "created_at")
    search_fields = ("inviter__first_name", "inviter__last_name", "invitee__first_name", "invitee__last_name")


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
        "kind",
        "description",
        "unit_price",
        "foerdersatz",
        "occurred_on",
        "deleted_at",
    )
    list_filter = ("kind", "deleted_at")
    search_fields = ("id", "description", "participant__first_name", "participant__last_name")
    readonly_fields = ("deleted_at", "deleted_by")

    @admin.display(description="Buchungsnr.", ordering="id")
    def booking_reference(self, charge: Charge) -> str:
        """Return the formatted booking reference for the admin changelist."""
        return charge.booking_reference


@admin.register(BookingAuditLog)
class BookingAuditLogAdmin(admin.ModelAdmin):
    list_display = ("participant", "charge", "action", "changed_by", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("charge__description", "participant__first_name", "participant__last_name")
    readonly_fields = ("participant", "charge", "action", "changed_by", "before", "after", "created_at")


admin.site.register(Payment)
admin.site.register(Expense)


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
    list_display = ("camp", "meal_date", "ordered_at", "ordered_by")
    list_filter = ("camp", "meal_date", "ordered_at")
    search_fields = ("camp__name", "ordered_by__username", "ordered_by__email")


admin.site.register(DrinkEntry)


class ReadOnlySnapshotAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
        import datetime

        from .models import Shift

        generated_count = 0
        skipped_count = 0
        for template in queryset:
            camp = template.camp
            if not camp.starts_on or not camp.ends_on:
                continue
            current_date = camp.starts_on
            exceptions_by_date = {ex.date: ex for ex in template.exceptions.all()}

            while current_date <= camp.ends_on:
                exception = exceptions_by_date.get(current_date)

                if exception and exception.is_skipped:
                    skipped_count += 1
                else:
                    slots = (
                        exception.custom_required_slots
                        if exception and exception.custom_required_slots is not None
                        else template.required_slots
                    )
                    start_t = (
                        exception.custom_start_time
                        if exception and exception.custom_start_time is not None
                        else template.start_time
                    )
                    end_t = (
                        exception.custom_end_time
                        if exception and exception.custom_end_time is not None
                        else template.end_time
                    )

                    Shift.objects.update_or_create(
                        camp=camp,
                        date=current_date,
                        name=template.name,
                        start_time=start_t,
                        defaults={
                            "end_time": end_t,
                            "required_slots": slots,
                        },
                    )
                    generated_count += 1
                current_date += datetime.timedelta(days=1)

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
