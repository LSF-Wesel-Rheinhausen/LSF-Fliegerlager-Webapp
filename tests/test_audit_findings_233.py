import os
from datetime import date

import pytest
from django.test import override_settings
from openpyxl import Workbook

from billing.exporters import (
    CSV_FORMULA_PREFIXES,
    _write_cost_center_sheet_from_snapshot,
    camp_workbook_response,
    safe_csv_cell,
)
from billing.forms import MealBookingForm
from billing.importers import normalize_row
from billing.models import PushSubscription
from billing.notification_views import queue_test_notification
from billing.roles import user_role

os.environ.setdefault("UPDATE_AGENT_TOKEN", "test-token")
from deployment_agent import RequestHandler

from tests.factories import CampFactory, ParticipantFactory, UserFactory


@pytest.mark.django_db
def test_xlsx_formula_escaping():
    assert safe_csv_cell("=1+1") == "'=1+1"
    assert safe_csv_cell("+123") == "'+123"
    assert safe_csv_cell("-123") == "'-123"
    assert safe_csv_cell("@CMD") == "'@CMD"

    camp = CampFactory()
    ParticipantFactory(camp=camp, last_name="=SUM(A1:A10)", first_name="Danger")
    resp = camp_workbook_response(camp)
    assert resp.status_code == 200


def test_cost_center_sheet_escapes_formula_cells():
    """The cost-center sheet must neutralise attacker-controlled names and descriptions.

    Regression for the M-4 gap: PR #250 escaped the settlement/participant sheets but
    left ``_write_cost_center_sheet_from_snapshot`` writing raw cells, so a participant's
    expense description or name could still land as a live formula in the XLSX export.
    """
    snapshot = [
        {
            "code": "cc-1",
            "label": "=cmd|'/c calc'!A1",
            "income": "10.00",
            "expense_total": "5.00",
            "balance": "5.00",
            "income_count": 1,
            "expense_count": 1,
            "income_details": [
                {
                    "meal_date": "2025-08-15",
                    "participant_name": '=HYPERLINK("http://evil")',
                    "family_member_name": "",
                    "description": "@SUM(1)",
                    "amount": "10.00",
                }
            ],
            "expense_details": [
                {
                    "paid_date": "2025-08-16",
                    "applicant_name": "+2+2",
                    "description": "-1-1",
                    "amount": "5.00",
                }
            ],
        }
    ]

    sheet = Workbook().active
    _write_cost_center_sheet_from_snapshot(sheet, snapshot)

    for row in sheet.iter_rows(values_only=True):
        for value in row:
            if isinstance(value, str):
                assert not value.lstrip().startswith(CSV_FORMULA_PREFIXES), value


@pytest.mark.django_db
def test_import_status_validation():
    row = normalize_row(
        {
            "first_name": "Test",
            "last_name": "User",
            "arrival_date": "2025-08-01",
            "departure_date": "2025-08-05",
            "hilfssatz": "0.1",
            "berufssatz": "0.2",
            "status": "INVALID_STATUS_STRING",
        },
        1,
    )
    assert any("Ungültiger Status" in err for err in row.errors)


@pytest.mark.django_db
def test_user_role_unassigned_user():
    user = UserFactory()
    assert user_role(user) == ""


@pytest.mark.django_db
@override_settings(WEB_PUSH_ENABLED=True)
def test_queue_test_notification_empty_categories():
    from billing.models import PushMessage

    user = UserFactory()
    sub = PushSubscription.objects.create(
        user=user,
        endpoint="https://example.com/push/123",
        p256dh="key",
        auth="auth",
        categories=[],
    )
    queue_test_notification(user, participant_owner=False, subscription_id=sub.pk)
    assert PushMessage.objects.filter(subscription=sub).count() == 1


@pytest.mark.django_db
def test_meal_booking_form_rejects_dates_when_camp_dates_missing():
    camp = CampFactory(starts_on=date(2025, 8, 10), ends_on=date(2025, 8, 20))
    participant = ParticipantFactory(camp=camp)
    form = MealBookingForm(data={"meal_dates": ["2025-08-01"]}, participant=participant)
    assert form.is_valid() is False


def test_deployment_agent_handles_non_ascii_auth_header(monkeypatch):
    class MockHandler:
        headers = {"Authorization": "Bearer öäü-non-ascii"}

    monkeypatch.setattr("deployment_agent.TOKEN", "secret-token")
    handler = MockHandler()
    handler.authorized = RequestHandler.authorized.__get__(handler, MockHandler)
    assert handler.authorized() is False
