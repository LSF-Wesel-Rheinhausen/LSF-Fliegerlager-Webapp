from django.contrib import admin

from .models import (
    BookingAuditLog,
    Camp,
    Charge,
    DrinkEntry,
    Expense,
    MealSignup,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    ParticipantPin,
    Payment,
    PriceRule,
    Settlement,
)


@admin.register(Camp)
class CampAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "foerdersatz", "meal_booking_cutoff_time", "is_active", "starts_on", "ends_on")
    search_fields = ("name",)


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "camp", "status", "hilfssatz", "berufssatz", "actual_nights", "is_child")
    list_filter = ("camp", "status", "is_child", "is_youth_group", "is_companion")
    search_fields = ("first_name", "last_name", "email")


admin.site.register(ParticipantPin)


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
        "foerderfaehig",
        "is_default",
    )
    list_filter = ("camp", "kind", "camp_flat_duration", "camp_flat_role", "foerderfaehig", "is_default")


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    list_display = (
        "booking_reference",
        "participant",
        "kind",
        "description",
        "unit_price",
        "foerderfaehig",
        "occurred_on",
        "deleted_at",
    )
    list_filter = ("kind", "foerderfaehig", "deleted_at")
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


admin.site.register(DrinkEntry)
admin.site.register(Settlement)
