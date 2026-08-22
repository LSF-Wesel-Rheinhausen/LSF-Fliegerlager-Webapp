from datetime import time
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone

from billing.kiosk_access import KIOSK_ACCESS_COOKIE_NAME, KIOSK_PARTICIPANT_SESSION_KEY, set_kiosk_access_cookie
from billing.models import BookingAuditLog, Camp, CampKioskAccess, Charge, Expense, Participant, Payment, PriceRule
from billing.permissions import EDITOR_GROUP, HUEBERS_GROUP
from tests.factories import (
    CampFactory,
    ChargeFactory,
    GroupFactory,
    ParticipantFactory,
    PriceRuleFactory,
    SuperUserFactory,
    UserFactory,
)


@pytest.fixture
def editor_user():
    user = UserFactory(username="editor")
    user.groups.add(GroupFactory(name=EDITOR_GROUP))
    return user


@pytest.fixture
def huebers_user():
    user = UserFactory(username="huebers")
    user.groups.add(GroupFactory(name=HUEBERS_GROUP))
    return user


@pytest.fixture
def admin_user():
    return SuperUserFactory(username="admin")


@pytest.fixture
def permission_dataset():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, first_name="Ada", last_name="Lovelace")
    rule = PriceRuleFactory(camp=camp, kind=PriceRule.Kind.DRINK, name="Cola", unit_price=Decimal("2.00"))
    charge = ChargeFactory(
        participant=participant,
        kind=Charge.Kind.OTHER,
        description="Editierbar",
        quantity=Decimal("1.00"),
        unit_price=Decimal("2.00"),
    )
    managed_user = UserFactory(username="managed", email="managed@example.test")
    return {
        "camp": camp,
        "participant": participant,
        "price_rule": rule,
        "charge": charge,
        "managed_user": managed_user,
    }


def _login_redirect(response):
    assert response.status_code == 302
    assert reverse("login") in response["Location"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "arg_getter"),
    [
        ("user-list", lambda data: []),
        ("user-create", lambda data: []),
        ("user-edit", lambda data: [data["managed_user"].pk]),
        ("user-password-reset", lambda data: [data["managed_user"].pk]),
        ("camp-create", lambda data: []),
        ("camp-edit", lambda data: [data["camp"].pk]),
        ("pin-set", lambda data: [data["participant"].pk]),
        ("charge-edit", lambda data: [data["charge"].pk]),
        ("price-rule-create", lambda data: [data["camp"].pk]),
        ("price-rules-manage", lambda data: [data["camp"].pk]),
        ("price-rule-edit", lambda data: [data["price_rule"].pk]),
    ],
)
def test_admin_only_get_views_reject_anonymous_and_editor(
    client,
    editor_user,
    permission_dataset,
    route_name,
    arg_getter,
):
    url = reverse(route_name, args=arg_getter(permission_dataset))

    _login_redirect(client.get(url))

    client.force_login(editor_user)
    _login_redirect(client.get(url))


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "arg_getter"),
    [
        ("user-list", lambda data: []),
        ("user-create", lambda data: []),
        ("user-edit", lambda data: [data["managed_user"].pk]),
        ("user-password-reset", lambda data: [data["managed_user"].pk]),
        ("camp-create", lambda data: []),
        ("camp-edit", lambda data: [data["camp"].pk]),
        ("pin-set", lambda data: [data["participant"].pk]),
        ("charge-edit", lambda data: [data["charge"].pk]),
        ("price-rule-create", lambda data: [data["camp"].pk]),
        ("price-rules-manage", lambda data: [data["camp"].pk]),
        ("price-rule-edit", lambda data: [data["price_rule"].pk]),
    ],
)
def test_admin_only_get_views_allow_admin(client, admin_user, permission_dataset, route_name, arg_getter):
    client.force_login(admin_user)

    response = client.get(reverse(route_name, args=arg_getter(permission_dataset)))

    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("filename", "content_type", "expected_disposition"),
    [
        ("rechnung.pdf", "application/pdf", "inline"),
        ("rechnung.png", "image/png", "inline"),
        ("rechnung.jpg", "image/jpeg", "inline"),
        ("rechnung.heic", "image/heic", "inline"),
        ("rechnung.legacy", "application/octet-stream", "attachment"),
    ],
)
def test_expense_receipt_download_sets_safe_preview_headers(
    client,
    editor_user,
    permission_dataset,
    filename,
    content_type,
    expected_disposition,
):
    receipt_content = b"editor receipt"
    expense = Expense.objects.create(
        camp=permission_dataset["camp"],
        participant=permission_dataset["participant"],
        category="Einkauf",
        description="Belegtest",
        amount=Decimal("7.50"),
        receipt=SimpleUploadedFile(filename, receipt_content, content_type=content_type),
    )
    client.force_login(editor_user)

    try:
        response = client.get(reverse("expense-receipt", args=[expense.pk]))

        assert response.status_code == 200
        assert response["Content-Disposition"].startswith(f'{expected_disposition}; filename="rechnung')
        assert response["Content-Type"] == content_type
        if content_type == "application/pdf":
            assert response["X-Frame-Options"] == "SAMEORIGIN"
            assert response["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'self'"
        assert b"".join(response.streaming_content) == receipt_content
    finally:
        expense.receipt.delete(save=False)


@pytest.mark.django_db
def test_expense_receipt_download_rejects_anonymous_without_kiosk_session(client, permission_dataset):
    expense = Expense.objects.create(
        camp=permission_dataset["camp"],
        participant=permission_dataset["participant"],
        category="Einkauf",
        description="Privater Beleg",
        amount=Decimal("7.50"),
        receipt=SimpleUploadedFile("privat.pdf", b"private receipt", content_type="application/pdf"),
    )

    try:
        response = client.get(reverse("expense-receipt", args=[expense.pk]))

        assert response.status_code == 403
    finally:
        expense.receipt.delete(save=False)


@pytest.mark.django_db
@pytest.mark.parametrize("caller", ["anonymous", "non_editor", "unauthorized_kiosk"])
def test_unauthorized_receipt_requests_do_not_reveal_receipt_existence(client, caller):
    camp = CampFactory(is_active=True, name=f"Oracle-Testlager-{caller}")
    owner = ParticipantFactory(camp=camp, first_name="Owner")
    stranger = ParticipantFactory(camp=camp, first_name="Stranger")
    with_receipt = Expense.objects.create(
        camp=camp,
        participant=owner,
        category="Einkauf",
        description="Mit Beleg",
        amount=Decimal("7.50"),
        receipt=SimpleUploadedFile("oracle.pdf", b"private receipt", content_type="application/pdf"),
    )
    without_receipt = Expense.objects.create(
        camp=camp,
        participant=owner,
        category="Einkauf",
        description="Ohne Beleg",
        amount=Decimal("7.50"),
    )
    if caller == "non_editor":
        client.force_login(UserFactory(username="non-editor"))
    elif caller == "unauthorized_kiosk":
        access = CampKioskAccess.objects.create(camp=camp)
        access.set_pin("246810")
        access.save()
        cookie_response = HttpResponse()
        set_kiosk_access_cookie(cookie_response, access)
        client.cookies[KIOSK_ACCESS_COOKIE_NAME] = cookie_response.cookies[KIOSK_ACCESS_COOKIE_NAME].value
        session = client.session
        session[KIOSK_PARTICIPANT_SESSION_KEY] = stranger.pk
        session.save()

    try:
        responses = [
            client.get(reverse("expense-receipt", args=[expense.pk])) for expense in (with_receipt, without_receipt)
        ]

        expected_status = 404 if caller == "unauthorized_kiosk" else 403
        assert responses[0].status_code == expected_status
        assert responses[1].status_code == expected_status
        assert responses[0].content == responses[1].content
        for response in responses:
            assert response["X-Frame-Options"] == "DENY"
            assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    finally:
        with_receipt.receipt.delete(save=False)


@pytest.mark.django_db
def test_unauthorized_kiosk_receipt_requests_do_not_reveal_expense_row_existence(client):
    camp = CampFactory(is_active=True, name="Expense-ID-Oracle-Testlager")
    owner = ParticipantFactory(camp=camp, first_name="Owner")
    stranger = ParticipantFactory(camp=camp, first_name="Stranger")
    expense = Expense.objects.create(
        camp=camp,
        participant=owner,
        category="Einkauf",
        description="Privater Beleg",
        amount=Decimal("7.50"),
        receipt=SimpleUploadedFile("existing.pdf", b"private receipt", content_type="application/pdf"),
    )
    access = CampKioskAccess.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    cookie_response = HttpResponse()
    set_kiosk_access_cookie(cookie_response, access)
    client.cookies[KIOSK_ACCESS_COOKIE_NAME] = cookie_response.cookies[KIOSK_ACCESS_COOKIE_NAME].value
    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = stranger.pk
    session.save()

    try:
        existing_response = client.get(reverse("expense-receipt", args=[expense.pk]))
        unknown_response = client.get(reverse("expense-receipt", args=[expense.pk + 1]))

        assert existing_response.status_code == 404
        assert unknown_response.status_code == 404
        assert existing_response.content == unknown_response.content
    finally:
        expense.receipt.delete(save=False)


@pytest.mark.django_db
def test_expense_receipt_download_returns_not_found_when_receipt_is_missing(client, editor_user, permission_dataset):
    expense = Expense.objects.create(
        camp=permission_dataset["camp"],
        participant=permission_dataset["participant"],
        category="Einkauf",
        description="Ohne Beleg",
        amount=Decimal("7.50"),
    )
    client.force_login(editor_user)

    response = client.get(reverse("expense-receipt", args=[expense.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_expense_receipt_download_returns_not_found_when_file_is_missing(client, editor_user, permission_dataset):
    expense = Expense.objects.create(
        camp=permission_dataset["camp"],
        participant=permission_dataset["participant"],
        category="Einkauf",
        description="Verwaister Beleg",
        amount=Decimal("7.50"),
        receipt=SimpleUploadedFile("verwaist.pdf", b"missing receipt", content_type="application/pdf"),
    )
    receipt_name = expense.receipt.name
    expense.receipt.delete(save=False)
    Expense.objects.filter(pk=expense.pk).update(receipt=receipt_name)
    client.force_login(editor_user)

    response = client.get(reverse("expense-receipt", args=[expense.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_shared_expense_approval_persists_selected_cost_center(client, editor_user, permission_dataset):
    expense = Expense.objects.create(
        camp=permission_dataset["camp"],
        participant=permission_dataset["participant"],
        category="Einkauf",
        description="Frühstück für alle",
        amount=Decimal("42.00"),
        status=Expense.Status.PENDING,
    )
    client.force_login(editor_user)

    response = client.post(
        reverse("shared-expense-approve", args=[expense.pk]),
        {
            "allocation_method": Expense.AllocationMethod.COST_CENTER,
            "cost_center": Expense.CostCenter.FOOD_BREAKFAST,
        },
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("camp-detail", args=[expense.camp_id])
    expense.refresh_from_db()
    assert expense.status == Expense.Status.APPROVED
    assert expense.allocation_method == Expense.AllocationMethod.COST_CENTER
    assert expense.cost_center == Expense.CostCenter.FOOD_BREAKFAST

    detail_response = client.get(reverse("camp-detail", args=[expense.camp_id]))

    assert detail_response.status_code == 200
    assert "Frühstück für alle".encode() in detail_response.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "arg_getter"),
    [
        ("camp-list", lambda data: []),
        ("camp-detail", lambda data: [data["camp"].pk]),
        ("camp-meal-overview", lambda data: [data["camp"].pk]),
        ("meal-cutoff-edit", lambda data: [data["camp"].pk]),
        ("participant-create", lambda data: [data["camp"].pk]),
        ("participant-detail", lambda data: [data["participant"].pk]),
        ("charge-create", lambda data: [data["participant"].pk]),
        ("payment-create", lambda data: [data["participant"].pk]),
        ("expense-create", lambda data: [data["camp"].pk]),
        ("participant-import", lambda data: [data["camp"].pk]),
        ("export-settlements-csv", lambda data: [data["camp"].pk]),
        ("export-drinks-csv", lambda data: [data["camp"].pk]),
        ("export-workbook", lambda data: [data["camp"].pk]),
        ("export-participant-pdf", lambda data: [data["participant"].pk]),
    ],
)
def test_editor_views_reject_anonymous(client, permission_dataset, route_name, arg_getter):
    response = client.get(reverse(route_name, args=arg_getter(permission_dataset)))

    _login_redirect(response)


@pytest.mark.django_db
@pytest.mark.parametrize("user_fixture_name", ["editor_user", "admin_user"])
@pytest.mark.parametrize(
    ("route_name", "arg_getter"),
    [
        ("camp-list", lambda data: []),
        ("camp-detail", lambda data: [data["camp"].pk]),
        ("camp-meal-overview", lambda data: [data["camp"].pk]),
        ("meal-cutoff-edit", lambda data: [data["camp"].pk]),
        ("participant-create", lambda data: [data["camp"].pk]),
        ("participant-detail", lambda data: [data["participant"].pk]),
        ("charge-create", lambda data: [data["participant"].pk]),
        ("payment-create", lambda data: [data["participant"].pk]),
        ("expense-create", lambda data: [data["camp"].pk]),
        ("participant-import", lambda data: [data["camp"].pk]),
        ("export-settlements-csv", lambda data: [data["camp"].pk]),
        ("export-drinks-csv", lambda data: [data["camp"].pk]),
        ("export-workbook", lambda data: [data["camp"].pk]),
        ("export-participant-pdf", lambda data: [data["participant"].pk]),
    ],
)
def test_editor_views_allow_editor_and_admin(
    client,
    request,
    permission_dataset,
    user_fixture_name,
    route_name,
    arg_getter,
):
    client.force_login(request.getfixturevalue(user_fixture_name))

    response = client.get(reverse(route_name, args=arg_getter(permission_dataset)))

    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "arg_getter"),
    [
        ("camp-list", lambda data: []),
        ("camp-meal-overview", lambda data: [data["camp"].pk]),
        ("meal-cutoff-edit", lambda data: [data["camp"].pk]),
        ("information-email-compose", lambda data: [data["camp"].pk]),
    ],
)
def test_huebers_can_access_meal_management_views(client, huebers_user, permission_dataset, route_name, arg_getter):
    client.force_login(huebers_user)

    response = client.get(reverse(route_name, args=arg_getter(permission_dataset)))

    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "arg_getter"),
    [
        ("camp-detail", lambda data: [data["camp"].pk]),
        ("participant-create", lambda data: [data["camp"].pk]),
        ("participant-detail", lambda data: [data["participant"].pk]),
        ("price-rules-manage", lambda data: [data["camp"].pk]),
        ("expense-create", lambda data: [data["camp"].pk]),
        ("export-workbook", lambda data: [data["camp"].pk]),
    ],
)
def test_huebers_cannot_access_billing_management_views(
    client, huebers_user, permission_dataset, route_name, arg_getter
):
    client.force_login(huebers_user)

    response = client.get(reverse(route_name, args=arg_getter(permission_dataset)))

    _login_redirect(response)


@pytest.mark.django_db
def test_huebers_can_update_meal_cutoff_only(client, huebers_user, permission_dataset):
    camp = permission_dataset["camp"]
    client.force_login(huebers_user)

    response = client.post(reverse("meal-cutoff-edit", args=[camp.pk]), {"meal_booking_cutoff_time": "18:00"})

    camp.refresh_from_db()
    assert response.status_code == 302
    assert response["Location"] == reverse("camp-meal-overview", args=[camp.pk])
    assert camp.meal_booking_cutoff_time == time(18, 0)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "arg_getter", "payload", "count_model"),
    [
        (
            "participant-create",
            lambda data: [data["camp"].pk],
            {
                "first_name": "Grace",
                "last_name": "Hopper",
                "status": Participant.Status.REGISTERED,
                "hilfssatz": "1.0000",
                "berufssatz": "1.0000",
                "booked_nights": "0",
                "actual_nights": "0",
            },
            Participant,
        ),
        (
            "charge-create",
            lambda data: [data["participant"].pk],
            {
                "kind": Charge.Kind.OTHER,
                "description": "Sonstiges",
                "quantity": "1.00",
                "unit_price": "5.00",
                "foerdersatz": "50",
            },
            Charge,
        ),
        (
            "payment-create",
            lambda data: [data["participant"].pk],
            {"amount": "5.00", "paid_on": "2026-07-01"},
            Payment,
        ),
        (
            "expense-create",
            lambda data: [data["camp"].pk],
            {
                "participant": lambda data: str(data["participant"].pk),
                "category": "Einkauf",
                "description": "Brötchen",
                "amount": "8.00",
                "reimbursable": "on",
            },
            Expense,
        ),
    ],
)
@pytest.mark.parametrize("user_fixture_name", ["editor_user", "admin_user"])
def test_editor_post_views_allow_editor_and_admin(
    client,
    request,
    permission_dataset,
    route_name,
    arg_getter,
    payload,
    count_model,
    user_fixture_name,
):
    resolved_payload = {key: value(permission_dataset) if callable(value) else value for key, value in payload.items()}
    before_count = count_model.objects.count()
    client.force_login(request.getfixturevalue(user_fixture_name))

    response = client.post(reverse(route_name, args=arg_getter(permission_dataset)), resolved_payload)

    assert response.status_code == 302
    assert count_model.objects.count() == before_count + 1


@pytest.mark.django_db
def test_expense_create_storage_failure_is_a_form_error(client, editor_user, permission_dataset, monkeypatch):
    client.force_login(editor_user)

    def fail_storage_save(*args, **kwargs):
        raise OSError("media storage unavailable")

    monkeypatch.setattr("django.core.files.storage.FileSystemStorage.save", fail_storage_save)
    response = client.post(
        reverse("expense-create", args=[permission_dataset["camp"].pk]),
        {
            "participant": permission_dataset["participant"].pk,
            "category": "Verbrauchsmaterial",
            "description": "Nicht gespeicherter Beleg",
            "amount": "12.50",
            "receipt": SimpleUploadedFile(
                "rechnung.pdf",
                b"%PDF-1.7\ntest receipt",
                content_type="application/pdf",
            ),
            "reimbursable": "on",
        },
    )

    assert response.status_code == 200
    assert "Rechnungsbeleg konnte nicht gespeichert werden" in response.content.decode()
    assert not Expense.objects.filter(description="Nicht gespeicherter Beleg").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "arg_getter", "payload", "count_model"),
    [
        (
            "camp-create",
            lambda data: [],
            {"name": "Adminlager", "year": "2027", "shift_ratio_per_night": "0.0"},
            Camp,
        ),
        (
            "price-rule-create",
            lambda data: [data["camp"].pk],
            {
                "kind": PriceRule.Kind.DRINK,
                "name": "Fanta",
                "unit_price": "2.50",
                "foerdersatz": "100",
                "applies_to_children": "on",
                "applies_to_adults": "on",
                "applies_to_companions": "on",
            },
            PriceRule,
        ),
    ],
)
def test_admin_post_views_reject_editor_and_allow_admin(
    client,
    editor_user,
    admin_user,
    permission_dataset,
    route_name,
    arg_getter,
    payload,
    count_model,
):
    url = reverse(route_name, args=arg_getter(permission_dataset))
    before_count = count_model.objects.count()
    client.force_login(editor_user)

    _login_redirect(client.post(url, payload))
    assert count_model.objects.count() == before_count

    client.force_login(admin_user)
    response = client.post(url, payload)

    assert response.status_code == 302
    assert count_model.objects.count() == before_count + 1


@pytest.mark.django_db
def test_admin_pin_post_views_reject_editor_and_allow_admin(client, editor_user, admin_user, permission_dataset):
    participant = permission_dataset["participant"]

    client.force_login(editor_user)
    _login_redirect(client.post(reverse("pin-set", args=[participant.pk]), {"pin": "1234"}))
    _login_redirect(client.post(reverse("pin-reset", args=[participant.pk])))
    participant.pin.refresh_from_db()
    assert participant.pin.check_pin("1234") is False
    assert participant.pin.must_set_pin is True

    client.force_login(admin_user)
    set_response = client.post(reverse("pin-set", args=[participant.pk]), {"pin": "1234"})
    reset_response = client.post(reverse("pin-reset", args=[participant.pk]))
    participant.pin.refresh_from_db()

    assert set_response.status_code == 302
    assert reset_response.status_code == 302
    assert participant.pin.must_set_pin is True


@pytest.mark.django_db
def test_admin_charge_delete_rejects_editor_and_allows_admin(client, editor_user, admin_user, permission_dataset):
    charge = permission_dataset["charge"]
    url = reverse("charge-delete", args=[charge.pk])

    client.force_login(editor_user)
    _login_redirect(client.post(url))
    assert Charge.objects.filter(pk=charge.pk).exists() is True

    client.force_login(admin_user)
    response = client.post(url)
    charge.refresh_from_db()

    assert response.status_code == 302
    assert Charge.objects.filter(pk=charge.pk).exists() is True
    assert charge.deleted_at is not None


@pytest.mark.django_db
def test_admin_booking_restore_rejects_editor_and_allows_admin(client, editor_user, admin_user, permission_dataset):
    participant = permission_dataset["participant"]
    charge = permission_dataset["charge"]
    charge.deleted_at = timezone.now()
    charge.save(update_fields=["deleted_at"])
    deleted_log = BookingAuditLog.objects.create(
        participant=participant,
        charge=charge,
        action=BookingAuditLog.Action.DELETED,
        before={
            "kind": Charge.Kind.OTHER,
            "description": "Wiederherstellbar",
            "quantity": "1.00",
            "unit_price": "2.00",
            "foerdersatz": "0.5000",
            "occurred_on": None,
        },
        after={},
    )
    url = reverse("booking-audit-restore", args=[deleted_log.pk])

    client.force_login(editor_user)
    _login_redirect(client.post(url))
    charge.refresh_from_db()
    deleted_log.refresh_from_db()
    assert deleted_log.charge == charge
    assert charge.deleted_at is not None

    client.force_login(admin_user)
    response = client.post(url)
    charge.refresh_from_db()
    deleted_log.refresh_from_db()

    assert response.status_code == 302
    assert deleted_log.charge == charge
    assert charge.deleted_at is None
