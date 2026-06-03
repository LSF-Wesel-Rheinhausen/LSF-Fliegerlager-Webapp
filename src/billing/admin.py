from django.contrib import admin

from .models import (
    BookingAuditLog,
    Camp,
    Charge,
    DrinkEntry,
    Expense,
    MealSignup,
    Participant,
    ParticipantPin,
    Payment,
    PriceRule,
    Settlement,
)


@admin.register(Camp)
class CampAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "foerdersatz", "is_active", "starts_on", "ends_on")
    search_fields = ("name",)


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "camp", "status", "hilfssatz", "berufssatz", "actual_nights", "is_child")
    list_filter = ("camp", "status", "is_child", "is_youth_group", "is_companion")
    search_fields = ("first_name", "last_name", "email")


admin.site.register(ParticipantPin)


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
    list_display = ("participant", "kind", "description", "unit_price", "foerderfaehig", "occurred_on")
    list_filter = ("kind", "foerderfaehig")


@admin.register(BookingAuditLog)
class BookingAuditLogAdmin(admin.ModelAdmin):
    list_display = ("participant", "charge", "action", "changed_by", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("charge__description", "participant__first_name", "participant__last_name")
    readonly_fields = ("participant", "charge", "action", "changed_by", "before", "after", "created_at")


admin.site.register(Payment)
admin.site.register(Expense)
admin.site.register(MealSignup)
admin.site.register(DrinkEntry)
admin.site.register(Settlement)
