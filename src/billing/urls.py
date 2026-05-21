from django.urls import path

from . import views


urlpatterns = [
    path("setup/", views.setup_first_admin, name="setup"),
    path("", views.camp_list, name="camp-list"),
    path("camps/new/", views.camp_create, name="camp-create"),
    path("camps/<int:camp_id>/", views.camp_detail, name="camp-detail"),
    path("camps/<int:camp_id>/participants/new/", views.participant_create, name="participant-create"),
    path("participants/<int:participant_id>/", views.participant_detail, name="participant-detail"),
    path("participants/<int:participant_id>/charges/new/", views.charge_create, name="charge-create"),
    path("participants/<int:participant_id>/payments/new/", views.payment_create, name="payment-create"),
    path("participants/<int:participant_id>/pin/reset/", views.pin_reset, name="pin-reset"),
    path("camps/<int:camp_id>/prices/new/", views.price_rule_create, name="price-rule-create"),
    path("camps/<int:camp_id>/expenses/new/", views.expense_create, name="expense-create"),
    path("camps/<int:camp_id>/import/", views.participant_import, name="participant-import"),
    path("camps/<int:camp_id>/export/settlements.csv", views.export_settlements_csv, name="export-settlements-csv"),
    path("camps/<int:camp_id>/export/drinks.csv", views.export_drinks_csv, name="export-drinks-csv"),
    path("camps/<int:camp_id>/export/workbook.xlsx", views.export_workbook, name="export-workbook"),
    path("participants/<int:participant_id>/export/settlement.pdf", views.export_participant_pdf, name="export-participant-pdf"),
]
