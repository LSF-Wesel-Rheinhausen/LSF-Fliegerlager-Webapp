import importlib

import pytest
from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.urls import reverse

from billing.forms import KioskCampAccessForm
from billing.permissions import EDITOR_GROUP
from tests.factories import (
    CampFactory,
    ExpenseFactory,
    GroupFactory,
    ParticipantFactory,
    SuperUserFactory,
    UserFactory,
)


@pytest.mark.django_db
def test_camp_kiosk_access_hashes_pin_and_rotates_generation():
    try:
        access_model = apps.get_model("billing", "CampKioskAccess")
    except LookupError:
        pytest.fail("CampKioskAccess model is missing")

    camp = CampFactory(is_active=True)
    admin = SuperUserFactory()
    access = access_model(camp=camp)

    access.set_pin("246810", changed_by=admin)
    first_generation = access.generation

    assert access.pin_hash != "246810"
    assert access.check_pin("246810") is True
    assert access.check_pin("000000") is False
    assert access.changed_by == admin

    access.revoke_all(changed_by=admin)

    assert access.generation != first_generation
    assert access.check_pin("246810") is True


@pytest.mark.django_db
def test_camp_kiosk_access_attempt_string_does_not_expose_client_key():
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    attempt_model = apps.get_model("billing", "CampKioskAccessAttempt")
    attempt = attempt_model.objects.create(
        access=access,
        client_key="a" * 64,
    )

    assert str(attempt) == f"Kiosk-PIN-Fehlversuche {camp}"
    assert attempt.client_key not in str(attempt)


@pytest.mark.django_db
def test_kiosk_access_cookie_is_persistent_hardened_and_server_validated(settings):
    try:
        kiosk_access = importlib.import_module("billing.kiosk_access")
    except ModuleNotFoundError:
        pytest.fail("billing.kiosk_access module is missing")

    settings.SESSION_COOKIE_SECURE = True
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    response = HttpResponse()

    kiosk_access.set_kiosk_access_cookie(response, access)

    cookie = response.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME]
    assert cookie["max-age"] == 30 * 24 * 60 * 60
    assert cookie["httponly"] is True
    assert cookie["secure"] is True
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/"
    assert "246810" not in cookie.value

    request = RequestFactory().get("/kiosk/")
    request.COOKIES[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = cookie.value

    assert kiosk_access.kiosk_access_from_request(request) == access


@pytest.mark.django_db
def test_rotated_generation_invalidates_previously_issued_cookie():
    kiosk_access = importlib.import_module("billing.kiosk_access")
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    response = HttpResponse()
    kiosk_access.set_kiosk_access_cookie(response, access)
    request = RequestFactory().get("/kiosk/")
    request.COOKIES[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = response.cookies[
        kiosk_access.KIOSK_ACCESS_COOKIE_NAME
    ].value

    access.revoke_all()
    access.save()

    assert kiosk_access.kiosk_access_from_request(request) is None


@pytest.mark.django_db
def test_expired_kiosk_access_cookie_is_rejected(settings):
    kiosk_access = importlib.import_module("billing.kiosk_access")
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    response = HttpResponse()
    kiosk_access.set_kiosk_access_cookie(response, access)
    request = RequestFactory().get("/kiosk/")
    request.COOKIES[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = response.cookies[
        kiosk_access.KIOSK_ACCESS_COOKIE_NAME
    ].value
    settings.KIOSK_ACCESS_COOKIE_AGE = -1

    assert kiosk_access.kiosk_access_from_request(request) is None


@pytest.mark.django_db
def test_tampered_cookie_cannot_submit_kiosk_data_and_clears_identity(client):
    CampFactory(is_active=True)
    kiosk_access = importlib.import_module("billing.kiosk_access")
    client.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = "manipulated"
    session = client.session
    session["kiosk_participant_id"] = 42
    session.save()

    response = client.post(
        reverse("kiosk-self-register"),
        {
            "first_name": "Ada",
            "last_name": "Lovelace",
        },
    )

    assert response.status_code == 403
    assert apps.get_model("billing", "Participant").objects.count() == 0
    assert "kiosk_participant_id" not in client.session
    assert response.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME]["max-age"] == 0


@pytest.mark.django_db
def test_kiosk_login_without_access_cookie_redirects_to_camp_pin(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()

    response = client.get(reverse("kiosk-login"))

    assert response.status_code == 302
    assert response["Location"] == "/kiosk/access/?next=%2Fkiosk%2Flogin%2F"


@pytest.mark.django_db
def test_kiosk_access_page_shows_only_the_shared_camp_pin_prompt(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()

    response = client.get("/kiosk/access/")

    assert response.status_code == 200
    assert b"Lager-PIN" in response.content
    assert b"Teilnehmer ausw\xc3\xa4hlen" not in response.content
    assert b"data-pwa-install" not in response.content


@pytest.mark.django_db
def test_correct_shared_pin_sets_cookie_and_redirects_to_safe_next(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    kiosk_access = importlib.import_module("billing.kiosk_access")

    response = client.post(
        "/kiosk/access/?next=%2Fkiosk%2Flogin%2F",
        {"pin": "246810"},
    )

    assert response.status_code == 302
    assert response["Location"] == "/kiosk/login/"
    assert kiosk_access.KIOSK_ACCESS_COOKIE_NAME in response.cookies


@pytest.mark.django_db
def test_valid_cookie_skips_shared_pin_prompt_on_first_load(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    kiosk_access = importlib.import_module("billing.kiosk_access")
    cookie_response = HttpResponse()
    kiosk_access.set_kiosk_access_cookie(cookie_response, access)
    client.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = cookie_response.cookies[
        kiosk_access.KIOSK_ACCESS_COOKIE_NAME
    ].value

    response = client.get("/kiosk/access/")

    assert response.status_code == 302
    assert response["Location"] == "/kiosk/"


@pytest.mark.parametrize("pin", ["12345", "1234567890123", "12ab56"])
def test_shared_camp_pin_accepts_only_six_to_twelve_digits(pin):
    form = KioskCampAccessForm({"pin": pin})

    assert form.is_valid() is False
    assert form.errors["pin"] == ["Die Lager-PIN muss aus 6 bis 12 Ziffern bestehen."]


@pytest.mark.django_db
def test_shared_pin_prompt_fails_closed_when_active_camp_has_no_access(client):
    CampFactory(is_active=True)
    kiosk_access = importlib.import_module("billing.kiosk_access")

    response = client.post("/kiosk/access/", {"pin": "246810"})

    assert response.status_code == 503
    assert b"noch nicht eingerichtet" in response.content
    assert kiosk_access.KIOSK_ACCESS_COOKIE_NAME not in response.cookies


@pytest.mark.django_db
def test_shared_pin_prompt_rate_limits_repeated_failures(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    kiosk_access = importlib.import_module("billing.kiosk_access")

    responses = [client.post("/kiosk/access/", {"pin": "000000"}) for _ in range(5)]
    blocked_response = client.post("/kiosk/access/", {"pin": "246810"})

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 429]
    assert blocked_response.status_code == 429
    assert blocked_response["Retry-After"] == "300"
    assert kiosk_access.KIOSK_ACCESS_COOKIE_NAME not in blocked_response.cookies


@pytest.mark.django_db
def test_shared_pin_rate_limit_survives_discarded_client_sessions():
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()

    responses = [
        Client().post(
            reverse("kiosk-access"),
            {"pin": "000000"},
            REMOTE_ADDR="203.0.113.42",
        )
        for _ in range(5)
    ]
    blocked_response = Client().post(
        reverse("kiosk-access"),
        {"pin": "246810"},
        REMOTE_ADDR="203.0.113.42",
    )

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 429]
    assert blocked_response.status_code == 429
    assert blocked_response["Retry-After"] == "300"


@pytest.mark.django_db
def test_shared_pin_rate_limit_distinguishes_clients_behind_trusted_proxy(settings):
    settings.KIOSK_ACCESS_TRUSTED_PROXY_ADDRESSES = frozenset({"127.0.0.1"})
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()

    first_client_responses = [
        Client().post(
            reverse("kiosk-access"),
            {"pin": "000000"},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.42",
        )
        for _ in range(5)
    ]
    second_client_response = Client().post(
        reverse("kiosk-access"),
        {"pin": "246810"},
        REMOTE_ADDR="127.0.0.1",
        HTTP_X_FORWARDED_FOR="198.51.100.17",
    )

    assert [response.status_code for response in first_client_responses] == [200, 200, 200, 200, 429]
    assert second_client_response.status_code == 302
    assert second_client_response["Location"] == "/kiosk/"


@pytest.mark.django_db
def test_shared_pin_rate_limit_ignores_forwarded_address_from_untrusted_peer(settings):
    settings.KIOSK_ACCESS_TRUSTED_PROXY_ADDRESSES = frozenset({"127.0.0.1"})
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()

    responses = [
        Client().post(
            reverse("kiosk-access"),
            {"pin": "000000"},
            REMOTE_ADDR="192.0.2.10",
            HTTP_X_FORWARDED_FOR=f"198.51.100.{index}",
        )
        for index in range(1, 6)
    ]
    blocked_response = Client().post(
        reverse("kiosk-access"),
        {"pin": "246810"},
        REMOTE_ADDR="192.0.2.10",
        HTTP_X_FORWARDED_FOR="198.51.100.99",
    )

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 429]
    assert blocked_response.status_code == 429


@pytest.mark.django_db
def test_shared_pin_rate_limit_rejects_ambiguous_forwarded_chain(settings):
    settings.KIOSK_ACCESS_TRUSTED_PROXY_ADDRESSES = frozenset({"127.0.0.1"})
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()

    responses = [
        Client().post(
            reverse("kiosk-access"),
            {"pin": "000000"},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR=f"198.51.100.{index}, 203.0.113.42",
        )
        for index in range(1, 6)
    ]
    blocked_response = Client().post(
        reverse("kiosk-access"),
        {"pin": "246810"},
        REMOTE_ADDR="127.0.0.1",
        HTTP_X_FORWARDED_FOR="198.51.100.99, 203.0.113.42",
    )

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 429]
    assert blocked_response.status_code == 429


@pytest.mark.django_db
def test_revoked_cookie_clears_participant_identity_before_redirect(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    kiosk_access = importlib.import_module("billing.kiosk_access")
    cookie_response = HttpResponse()
    kiosk_access.set_kiosk_access_cookie(cookie_response, access)
    client.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = cookie_response.cookies[
        kiosk_access.KIOSK_ACCESS_COOKIE_NAME
    ].value
    identity_keys = (
        "kiosk_participant_id",
        "kiosk_family_member_id",
        "kiosk_pin_setup_participant_id",
        "kiosk_pin_setup_family_member_id",
    )
    session = client.session
    for key in identity_keys:
        session[key] = 42
    session.save()

    access.revoke_all()
    access.save()
    response = client.get(reverse("kiosk-home"))

    assert response.status_code == 302
    assert response["Location"].startswith("/kiosk/access/")
    assert all(key not in client.session for key in identity_keys)
    assert response.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME]["max-age"] == 0


@pytest.mark.django_db
def test_direct_pin_prompt_clears_identity_bound_to_revoked_cookie(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    kiosk_access = importlib.import_module("billing.kiosk_access")
    cookie_response = HttpResponse()
    kiosk_access.set_kiosk_access_cookie(cookie_response, access)
    client.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = cookie_response.cookies[
        kiosk_access.KIOSK_ACCESS_COOKIE_NAME
    ].value
    session = client.session
    session["kiosk_participant_id"] = 42
    session.save()
    access.revoke_all()
    access.save()

    response = client.get(reverse("kiosk-access"))

    assert response.status_code == 200
    assert "kiosk_participant_id" not in client.session
    assert response.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME]["max-age"] == 0


@pytest.mark.django_db
def test_kiosk_access_responses_are_not_cacheable_and_vary_by_cookie(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    kiosk_access = importlib.import_module("billing.kiosk_access")

    denied_response = client.get(reverse("kiosk-login"))
    cookie_response = HttpResponse()
    kiosk_access.set_kiosk_access_cookie(cookie_response, access)
    client.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = cookie_response.cookies[
        kiosk_access.KIOSK_ACCESS_COOKIE_NAME
    ].value
    allowed_response = client.get(reverse("kiosk-login"))

    for response in (denied_response, allowed_response):
        assert "no-store" in response["Cache-Control"]
        assert "Cookie" in response["Vary"]


@pytest.mark.django_db
def test_kiosk_session_cannot_download_receipt_without_valid_camp_cookie(client):
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)
    expense = ExpenseFactory(
        camp=camp,
        participant=participant,
        receipt=SimpleUploadedFile("beleg.pdf", b"private receipt", content_type="application/pdf"),
    )
    session = client.session
    session["kiosk_participant_id"] = participant.pk
    session.save()

    try:
        response = client.get(reverse("expense-receipt", args=[expense.pk]))

        assert response.status_code == 403
    finally:
        expense.receipt.delete(save=False)


@pytest.mark.django_db
def test_admin_can_configure_shared_camp_pin_without_storing_plaintext(client):
    camp = CampFactory(is_active=True)
    admin = SuperUserFactory()
    client.force_login(admin)

    response = client.post(
        reverse("camp-kiosk-access-settings", args=[camp.pk]),
        {
            "pin": "246810",
            "pin_repeat": "246810",
        },
    )

    assert response.status_code == 302
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.get(camp=camp)
    assert access.pin_hash != "246810"
    assert access.check_pin("246810") is True
    assert access.changed_by == admin


@pytest.mark.django_db
def test_admin_revoke_invalidates_all_issued_camp_cookies(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    original_generation = access.generation
    kiosk_access = importlib.import_module("billing.kiosk_access")
    cookie_response = HttpResponse()
    kiosk_access.set_kiosk_access_cookie(cookie_response, access)
    issued_cookie = cookie_response.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME].value
    kiosk_clients = [Client(), Client()]
    for kiosk_client in kiosk_clients:
        kiosk_client.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = issued_cookie

    admin = SuperUserFactory()
    client.force_login(admin)
    response = client.post(reverse("camp-kiosk-access-revoke", args=[camp.pk]))

    assert response.status_code == 302
    access.refresh_from_db()
    assert access.generation != original_generation
    assert access.changed_by == admin
    for kiosk_client in kiosk_clients:
        denied_response = kiosk_client.get(reverse("kiosk-login"))
        assert denied_response.status_code == 302
        assert denied_response["Location"].startswith("/kiosk/access/")


@pytest.mark.django_db
def test_reactivating_camp_does_not_restore_previously_issued_cookie(client):
    first_camp = CampFactory(name="Erstes Lager", year=2025, is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=first_camp)
    access.set_pin("246810")
    access.save()
    kiosk_access = importlib.import_module("billing.kiosk_access")
    cookie_response = HttpResponse()
    kiosk_access.set_kiosk_access_cookie(cookie_response, access)
    client.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = cookie_response.cookies[
        kiosk_access.KIOSK_ACCESS_COOKIE_NAME
    ].value

    CampFactory(name="Zweites Lager", year=2026, is_active=True)
    first_camp.refresh_from_db()
    first_camp.is_active = True
    first_camp.save()
    response = client.get(reverse("kiosk-login"))

    assert response.status_code == 302
    assert response["Location"].startswith("/kiosk/access/")


@pytest.mark.django_db
def test_deleting_active_camp_does_not_restore_cookie_for_reactivated_camp(client):
    remaining_camp = CampFactory(name="Verbleibendes Lager", year=2025, is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=remaining_camp)
    access.set_pin("246810")
    access.save()
    kiosk_access = importlib.import_module("billing.kiosk_access")
    cookie_response = HttpResponse()
    kiosk_access.set_kiosk_access_cookie(cookie_response, access)
    client.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = cookie_response.cookies[
        kiosk_access.KIOSK_ACCESS_COOKIE_NAME
    ].value
    active_camp = CampFactory(name="Aktives Lager", year=2026, is_active=True)

    active_camp.delete()
    response = client.get(reverse("kiosk-login"))

    remaining_camp.refresh_from_db()
    assert remaining_camp.is_active is True
    assert response.status_code == 302
    assert response["Location"].startswith("/kiosk/access/")


@pytest.mark.django_db
def test_shared_pin_rejects_external_and_cross_mode_redirect_targets(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()

    external_response = client.post(
        "/kiosk/access/?next=https%3A%2F%2Fevil.example%2F",
        {"pin": "246810"},
    )
    client.cookies.clear()
    cross_mode_response = client.post(
        "/kiosk/access/?next=%2Fcentral%2Fkiosk%2F",
        {"pin": "246810"},
    )
    client.cookies.clear()
    traversal_response = client.post(
        "/kiosk/access/?next=%2Fkiosk%2F..%2Flogin%2F",
        {"pin": "246810"},
    )

    assert external_response["Location"] == reverse("kiosk-home")
    assert cross_mode_response["Location"] == reverse("kiosk-home")
    assert traversal_response["Location"] == reverse("kiosk-home")


@pytest.mark.django_db
def test_central_kiosk_redirects_to_matching_shared_pin_prompt(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()

    response = client.get(reverse("central-kiosk-shifts"))

    assert response.status_code == 302
    assert response["Location"] == "/central/kiosk/access/?next=%2Fcentral%2Fkiosk%2Fshifts%2F"


@pytest.mark.django_db
def test_kiosk_business_post_without_cookie_is_rejected_before_side_effect(client):
    CampFactory(is_active=True)
    participant_model = apps.get_model("billing", "Participant")

    response = client.post(
        reverse("kiosk-self-register"),
        {
            "first_name": "Ada",
            "last_name": "Lovelace",
        },
    )

    assert response.status_code == 403
    assert participant_model.objects.count() == 0


@pytest.mark.django_db
def test_kiosk_help_requires_shared_camp_cookie(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()

    response = client.get(reverse("user-guide"))

    assert response.status_code == 302
    assert response["Location"] == "/kiosk/access/?next=%2Fhelp%2F"


@pytest.mark.django_db
def test_shared_pin_returns_to_kiosk_help_after_authorization(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()

    response = client.post("/kiosk/access/?next=%2Fhelp%2F", {"pin": "246810"})

    assert response.status_code == 302
    assert response["Location"] == reverse("user-guide")


@pytest.mark.django_db
def test_editor_cannot_configure_or_revoke_shared_camp_pin(client):
    camp = CampFactory(is_active=True)
    editor = UserFactory()
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    client.force_login(editor)

    settings_response = client.get(reverse("camp-kiosk-access-settings", args=[camp.pk]))
    revoke_response = client.post(reverse("camp-kiosk-access-revoke", args=[camp.pk]))

    assert settings_response.status_code == 302
    assert reverse("login") in settings_response["Location"]
    assert revoke_response.status_code == 302
    assert reverse("login") in revoke_response["Location"]


@pytest.mark.django_db
def test_changing_shared_pin_invalidates_old_cookie_and_old_pin(client):
    camp = CampFactory(is_active=True)
    access_model = apps.get_model("billing", "CampKioskAccess")
    access = access_model.objects.create(camp=camp)
    access.set_pin("246810")
    access.save()
    kiosk_access = importlib.import_module("billing.kiosk_access")
    cookie_response = HttpResponse()
    kiosk_access.set_kiosk_access_cookie(cookie_response, access)
    issued_cookie = cookie_response.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME].value

    admin = SuperUserFactory()
    client.force_login(admin)
    client.cookies[kiosk_access.KIOSK_ACCESS_COOKIE_NAME] = issued_cookie
    response = client.post(
        reverse("camp-kiosk-access-settings", args=[camp.pk]),
        {
            "pin": "135790",
            "pin_repeat": "135790",
        },
    )

    assert response.status_code == 302
    access.refresh_from_db()
    assert access.check_pin("246810") is False
    assert access.check_pin("135790") is True
    denied_response = client.get(reverse("kiosk-login"))
    assert denied_response.status_code == 302
    assert denied_response["Location"].startswith("/kiosk/access/")
