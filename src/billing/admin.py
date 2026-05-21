from django.contrib import admin

from .models import Camp, Charge, DrinkEntry, Expense, MealSignup, Participant, ParticipantPin, Payment, PriceRule, Settlement


@admin.register(Camp)
class CampAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "is_active", "starts_on", "ends_on")
    search_fields = ("name",)


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "camp", "status", "actual_nights", "is_child")
    list_filter = ("camp", "status", "is_child", "is_youth_group", "is_companion")
    search_fields = ("first_name", "last_name", "email")


admin.site.register(ParticipantPin)
admin.site.register(PriceRule)
admin.site.register(Charge)
admin.site.register(Payment)
admin.site.register(Expense)
admin.site.register(MealSignup)
admin.site.register(DrinkEntry)
admin.site.register(Settlement)
