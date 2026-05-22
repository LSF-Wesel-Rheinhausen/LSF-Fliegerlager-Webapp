from django.contrib import admin

from .models import (
    Camp,
    Charge,
    DrinkEntry,
    Expense,
    MealSignup,
    OvernightCategory,
    Participant,
    ParticipantPin,
    Payment,
    PriceRule,
    Settlement,
    SettlementRun,
)


@admin.register(Camp)
class CampAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "foerdersatz", "is_active", "starts_on", "ends_on")
    search_fields = ("name",)


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = (
        "last_name",
        "first_name",
        "camp",
        "status",
        "overnight_category",
        "actual_nights",
        "is_child",
    )
    list_filter = ("camp", "status", "is_child", "is_youth_group", "is_companion")
    search_fields = ("first_name", "last_name", "email")


@admin.register(OvernightCategory)
class OvernightCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "camp", "is_active")
    list_filter = ("camp", "is_active")
    search_fields = ("name", "description")


admin.site.register(ParticipantPin)


@admin.register(PriceRule)
class PriceRuleAdmin(admin.ModelAdmin):
    list_display = (
        "camp",
        "kind",
        "name",
        "overnight_category",
        "unit_price",
        "foerderfaehig",
        "is_default",
    )
    list_filter = ("camp", "kind", "overnight_category", "foerderfaehig", "is_default")


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    list_display = ("participant", "kind", "description", "unit_price", "foerderfaehig", "occurred_on")
    list_filter = ("kind", "foerderfaehig")


admin.site.register(Payment)
admin.site.register(Expense)
admin.site.register(MealSignup)
admin.site.register(DrinkEntry)


@admin.register(SettlementRun)
class SettlementRunAdmin(admin.ModelAdmin):
    list_display = ("camp", "created_at", "created_by", "participant_count", "total_due", "balance")
    list_filter = ("camp",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ("participant", "run", "total_due", "total_paid", "total_advanced", "balance", "created_at")
    list_filter = ("run__camp",)
    search_fields = ("participant__first_name", "participant__last_name")
