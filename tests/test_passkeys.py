import importlib
import json
import logging
import time
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.staticfiles import finders
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, override_settings
from webauthn.helpers.exceptions import InvalidAuthenticationResponse

from tests.factories import UserFactory


def test_passkeys_are_disabled_without_explicit_deployment_configuration():
    assert getattr(settings, "PASSKEY_ENABLED", None) is False


PASSKEY_SETTINGS = override_settings(
    PASSKEY_ENABLED=True,
    PASSKEY_RP_ID="localhost",
    PASSKEY_RP_NAME="Fliegerlager Test",
    PASSKEY_ORIGIN="http://localhost:8000",
    PASSKEY_CHALLENGE_TTL_SECONDS=300,
)


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_registration_options_require_user_verification_and_store_the_challenge():
    try:
        passkeys = importlib.import_module("billing.passkeys")
    except ModuleNotFoundError:
        passkeys = None
    assert passkeys is not None
    assert callable(getattr(passkeys, "begin_passkey_registration", None))

    user = UserFactory(username="admin", email="admin@example.test")
    session = {}
    options = json.loads(passkeys.begin_passkey_registration(user, session))

    assert options["rp"] == {"id": "localhost", "name": "Fliegerlager Test"}
    assert options["user"]["name"] == "admin@example.test"
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert session[passkeys.REGISTRATION_CHALLENGE_SESSION_KEY]["challenge"] == options["challenge"]
    assert session[passkeys.REGISTRATION_CHALLENGE_SESSION_KEY]["user_id"] == user.pk


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_registration_options_exclude_existing_credentials():
    passkeys = importlib.import_module("billing.passkeys")
    credential_model = apps.get_model("billing", "PasskeyCredential")
    user = UserFactory()
    credential_model.objects.create(
        user=user,
        name="Existing",
        credential_id=b"existing-credential",
        public_key=b"public-key",
    )

    options = json.loads(passkeys.begin_passkey_registration(user, {}))

    assert options["excludeCredentials"] == [
        {
            "id": "ZXhpc3RpbmctY3JlZGVudGlhbA",
            "type": "public-key",
        }
    ]


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_registration_verifies_and_persists_only_verified_credential_data(monkeypatch):
    passkeys = importlib.import_module("billing.passkeys")
    assert callable(getattr(passkeys, "finish_passkey_registration", None))
    user = UserFactory()
    session = {
        passkeys.REGISTRATION_CHALLENGE_SESSION_KEY: {
            "challenge": "cmVnaXN0cmF0aW9uLWNoYWxsZW5nZQ",
            "user_id": user.pk,
            "created_at": int(time.time()),
        }
    }
    captured = {}

    def fake_verify_registration_response(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            credential_id=b"verified-credential",
            credential_public_key=b"verified-public-key",
            sign_count=7,
            credential_device_type=SimpleNamespace(value="multi_device"),
            credential_backed_up=True,
        )

    monkeypatch.setattr(passkeys, "verify_registration_response", fake_verify_registration_response)
    credential = passkeys.finish_passkey_registration(
        user,
        session,
        {"id": "untrusted-id", "response": {"transports": ["internal", "hybrid"]}},
        name="MacBook",
    )

    assert captured["expected_challenge"] == b"registration-challenge"
    assert captured["expected_rp_id"] == "localhost"
    assert captured["expected_origin"] == "http://localhost:8000"
    assert captured["require_user_verification"] is True
    assert credential.credential_id == b"verified-credential"
    assert credential.public_key == b"verified-public-key"
    assert credential.sign_count == 7
    assert credential.transports == ["internal", "hybrid"]
    assert credential.backed_up is True
    assert passkeys.REGISTRATION_CHALLENGE_SESSION_KEY not in session


@PASSKEY_SETTINGS
def test_authentication_options_are_discoverable_and_require_user_verification():
    passkeys = importlib.import_module("billing.passkeys")
    assert callable(getattr(passkeys, "begin_passkey_authentication", None))
    session = {}

    options = json.loads(passkeys.begin_passkey_authentication(session))

    assert options["rpId"] == "localhost"
    assert options["allowCredentials"] == []
    assert options["userVerification"] == "required"
    assert session[passkeys.AUTHENTICATION_CHALLENGE_SESSION_KEY]["challenge"] == options["challenge"]


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_authentication_verifies_the_credential_and_updates_its_counter(monkeypatch):
    passkeys = importlib.import_module("billing.passkeys")
    assert callable(getattr(passkeys, "finish_passkey_authentication", None))
    credential_model = apps.get_model("billing", "PasskeyCredential")
    user = UserFactory()
    credential = credential_model.objects.create(
        user=user,
        name="Security Key",
        credential_id=b"stored-credential",
        public_key=b"stored-public-key",
        sign_count=3,
    )
    session = {
        passkeys.AUTHENTICATION_CHALLENGE_SESSION_KEY: {
            "challenge": "YXV0aGVudGljYXRpb24tY2hhbGxlbmdl",
            "created_at": int(time.time()),
        }
    }
    captured = {}

    def fake_verify_authentication_response(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            credential_id=b"stored-credential",
            new_sign_count=4,
            credential_device_type=SimpleNamespace(value="single_device"),
            credential_backed_up=False,
        )

    monkeypatch.setattr(passkeys, "verify_authentication_response", fake_verify_authentication_response)
    authenticated_user = passkeys.finish_passkey_authentication(
        session,
        {"id": "c3RvcmVkLWNyZWRlbnRpYWw", "response": {}},
    )

    credential.refresh_from_db()
    assert authenticated_user == user
    assert captured["expected_challenge"] == b"authentication-challenge"
    assert captured["credential_public_key"] == b"stored-public-key"
    assert captured["credential_current_sign_count"] == 3
    assert captured["require_user_verification"] is True
    assert credential.sign_count == 4
    assert credential.last_used_at is not None
    assert passkeys.AUTHENTICATION_CHALLENGE_SESSION_KEY not in session


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_passkey_management_requires_login_and_lists_only_own_credentials(client):
    credential_model = apps.get_model("billing", "PasskeyCredential")
    user = UserFactory()
    other_user = UserFactory()
    credential_model.objects.create(
        user=user,
        name="Own MacBook",
        credential_id=b"own-credential",
        public_key=b"own-public-key",
    )
    credential_model.objects.create(
        user=other_user,
        name="Other Security Key",
        credential_id=b"other-credential",
        public_key=b"other-public-key",
    )

    anonymous_response = client.get("/passkeys/")
    client.force_login(user)
    response = client.get("/passkeys/")

    assert anonymous_response.status_code == 302
    assert anonymous_response["Location"] == "/login/?next=/passkeys/"
    assert response.status_code == 200
    assert b"Own MacBook" in response.content
    assert b"Other Security Key" not in response.content


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_passkey_option_endpoints_enforce_methods_and_registration_login(client):
    user = UserFactory()

    auth_get = client.get("/passkeys/authentication/options/")
    auth_post = client.post("/passkeys/authentication/options/")
    anonymous_registration = client.post("/passkeys/registration/options/")
    client.force_login(user)
    registration_post = client.post("/passkeys/registration/options/")

    assert auth_get.status_code == 405
    assert auth_post.status_code == 200
    assert auth_post["Content-Type"] == "application/json"
    assert json.loads(auth_post.content)["userVerification"] == "required"
    assert anonymous_registration.status_code == 302
    assert registration_post.status_code == 200
    assert json.loads(registration_post.content)["authenticatorSelection"]["residentKey"] == "required"


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_registration_verify_endpoint_persists_the_authenticated_users_passkey(client, monkeypatch, caplog):
    passkeys = importlib.import_module("billing.passkeys")
    caplog.set_level(logging.INFO, logger="billing.passkey_views")
    credential_model = apps.get_model("billing", "PasskeyCredential")
    user = UserFactory()
    client.force_login(user)
    session = client.session
    session[passkeys.REGISTRATION_CHALLENGE_SESSION_KEY] = {
        "challenge": "cmVnaXN0cmF0aW9uLWNoYWxsZW5nZQ",
        "user_id": user.pk,
        "created_at": int(time.time()),
    }
    session.save()
    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **_kwargs: SimpleNamespace(
            credential_id=b"new-credential",
            credential_public_key=b"new-public-key",
            sign_count=0,
            credential_device_type=SimpleNamespace(value="multi_device"),
            credential_backed_up=True,
        ),
    )

    response = client.post(
        "/passkeys/registration/verify/",
        data=json.dumps(
            {
                "name": "  MacBook Touch ID  ",
                "credential": {"id": "bmV3LWNyZWRlbnRpYWw", "response": {"transports": ["internal"]}},
            }
        ),
        content_type="application/json",
    )

    stored = credential_model.objects.get(user=user)
    assert response.status_code == 201
    assert response.json() == {"id": stored.pk, "name": "MacBook Touch ID"}
    assert stored.name == "MacBook Touch ID"
    assert stored.credential_id == b"new-credential"
    audit_record = next(record for record in caplog.records if record.msg == "passkey_registration_succeeded")
    assert audit_record.user_id == user.pk
    assert audit_record.request_id


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_authentication_verify_endpoint_creates_a_django_session(client, monkeypatch):
    passkeys = importlib.import_module("billing.passkeys")
    credential_model = apps.get_model("billing", "PasskeyCredential")
    user = UserFactory()
    credential_model.objects.create(
        user=user,
        name="Security Key",
        credential_id=b"login-credential",
        public_key=b"login-public-key",
    )
    session = client.session
    session[passkeys.AUTHENTICATION_CHALLENGE_SESSION_KEY] = {
        "challenge": "YXV0aGVudGljYXRpb24tY2hhbGxlbmdl",
        "created_at": int(time.time()),
    }
    session.save()
    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        lambda **_kwargs: SimpleNamespace(
            credential_id=b"login-credential",
            new_sign_count=1,
            credential_device_type=SimpleNamespace(value="single_device"),
            credential_backed_up=False,
        ),
    )

    response = client.post(
        "/passkeys/authentication/verify/",
        data=json.dumps(
            {
                "next": "https://attacker.example/phish",
                "credential": {"id": "bG9naW4tY3JlZGVudGlhbA", "response": {}},
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {"redirect": "/camps/"}
    assert int(client.session[SESSION_KEY]) == user.pk


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_authentication_rejects_a_challenge_timestamp_from_the_future(client, monkeypatch):
    passkeys = importlib.import_module("billing.passkeys")
    credential_model = apps.get_model("billing", "PasskeyCredential")
    user = UserFactory()
    credential_model.objects.create(
        user=user,
        name="Security Key",
        credential_id=b"future-credential",
        public_key=b"future-public-key",
    )
    session = client.session
    session[passkeys.AUTHENTICATION_CHALLENGE_SESSION_KEY] = {
        "challenge": "YXV0aGVudGljYXRpb24tY2hhbGxlbmdl",
        "created_at": int(time.time()) + 60,
    }
    session.save()
    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        lambda **_kwargs: SimpleNamespace(
            credential_id=b"future-credential",
            new_sign_count=1,
            credential_device_type=SimpleNamespace(value="single_device"),
            credential_backed_up=False,
        ),
    )

    response = client.post(
        "/passkeys/authentication/verify/",
        data=json.dumps({"credential": {"id": "ZnV0dXJlLWNyZWRlbnRpYWw", "response": {}}}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert SESSION_KEY not in client.session


@override_settings(
    PASSKEY_ENABLED=True,
    PASSKEY_RP_ID="example.test",
    PASSKEY_RP_NAME="Fliegerlager Test",
    PASSKEY_ORIGIN="http://example.test",
)
def test_passkey_configuration_rejects_insecure_non_local_origin():
    passkeys = importlib.import_module("billing.passkeys")

    with pytest.raises(ImproperlyConfigured, match="HTTPS"):
        passkeys.begin_passkey_authentication({})


@pytest.mark.parametrize(
    ("rp_id", "origin"),
    [
        ("127.0.0.1", "http://127.0.0.1:8000"),
        ("::1", "http://[::1]:8000"),
    ],
)
def test_passkey_configuration_rejects_ip_address_rp_ids(rp_id: str, origin: str) -> None:
    passkeys = importlib.import_module("billing.passkeys")

    with override_settings(
        PASSKEY_ENABLED=True,
        PASSKEY_RP_ID=rp_id,
        PASSKEY_RP_NAME="Fliegerlager Test",
        PASSKEY_ORIGIN=origin,
    ):
        with pytest.raises(ImproperlyConfigured, match="domain name"):
            passkeys.begin_passkey_authentication({})


@override_settings(
    PASSKEY_ENABLED=True,
    PASSKEY_RP_ID="example.test",
    PASSKEY_RP_NAME="Fliegerlager Test",
    PASSKEY_ORIGIN="https://user@example.test",
)
def test_passkey_configuration_rejects_origin_with_embedded_credentials():
    passkeys = importlib.import_module("billing.passkeys")

    with pytest.raises(ImproperlyConfigured, match="credentials"):
        passkeys.begin_passkey_authentication({})


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_user_can_delete_only_their_own_passkey(client):
    credential_model = apps.get_model("billing", "PasskeyCredential")
    user = UserFactory()
    other_user = UserFactory()
    own_credential = credential_model.objects.create(
        user=user,
        name="Own Key",
        credential_id=b"own-delete-credential",
        public_key=b"own-public-key",
    )
    other_credential = credential_model.objects.create(
        user=other_user,
        name="Other Key",
        credential_id=b"other-delete-credential",
        public_key=b"other-public-key",
    )
    client.force_login(user)

    foreign_response = client.post(f"/passkeys/{other_credential.pk}/delete/")
    own_response = client.post(f"/passkeys/{own_credential.pk}/delete/")

    assert foreign_response.status_code == 404
    assert own_response.status_code == 302
    assert own_response["Location"] == "/passkeys/"
    assert credential_model.objects.filter(pk=own_credential.pk).exists() is False
    assert credential_model.objects.filter(pk=other_credential.pk).exists() is True


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_login_page_offers_passkey_login_only_when_enabled(client):
    UserFactory()

    enabled_response = client.get("/login/")
    with override_settings(PASSKEY_ENABLED=False):
        disabled_response = client.get("/login/")

    assert b"data-passkey-login" in enabled_response.content
    assert b'data-options-url="/passkeys/authentication/options/"' in enabled_response.content
    assert b"data-passkey-login" not in disabled_response.content


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_passkey_management_exposes_registration_and_confirmed_deletion_controls(client):
    credential_model = apps.get_model("billing", "PasskeyCredential")
    user = UserFactory()
    credential = credential_model.objects.create(
        user=user,
        name="Security Key",
        credential_id=b"managed-credential",
        public_key=b"managed-public-key",
    )
    client.force_login(user)

    response = client.get("/passkeys/")

    assert b"data-passkey-register" in response.content
    assert b'name="passkey_name"' in response.content
    assert f'action="/passkeys/{credential.pk}/delete/"'.encode() in response.content
    assert b'data-confirm="Diesen Passkey wirklich entfernen?"' in response.content


def test_passkey_browser_module_is_discoverable_by_staticfiles():
    assert finders.find("billing/passkeys.js")


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_authenticated_navigation_links_to_passkey_management_only_when_enabled(client):
    user = UserFactory()
    client.force_login(user)

    enabled_response = client.get("/camps/")
    with override_settings(PASSKEY_ENABLED=False):
        disabled_response = client.get("/camps/")

    assert b'href="/passkeys/"' in enabled_response.content
    assert b'href="/passkeys/"' not in disabled_response.content


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_passkey_json_endpoints_require_csrf_tokens():
    csrf_client = Client(enforce_csrf_checks=True)
    user = UserFactory()

    auth_options_response = csrf_client.post("/passkeys/authentication/options/")
    csrf_client.force_login(user)
    registration_options_response = csrf_client.post("/passkeys/registration/options/")

    assert auth_options_response.status_code == 403
    assert registration_options_response.status_code == 403


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_authentication_rejects_missing_or_replayed_challenges_with_a_generic_error(client):
    response = client.post(
        "/passkeys/authentication/verify/",
        data=json.dumps({"credential": {"id": "dW5rbm93bg", "response": {}}}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Anmeldung mit Passkey fehlgeschlagen."}
    assert SESSION_KEY not in client.session


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_inactive_user_cannot_authenticate_with_a_stored_passkey(monkeypatch):
    passkeys = importlib.import_module("billing.passkeys")
    credential_model = apps.get_model("billing", "PasskeyCredential")
    user = UserFactory(is_active=False)
    credential_model.objects.create(
        user=user,
        name="Disabled account key",
        credential_id=b"inactive-credential",
        public_key=b"inactive-public-key",
    )
    verifier_called = False

    def unexpected_verifier(**_kwargs):
        nonlocal verifier_called
        verifier_called = True

    monkeypatch.setattr(passkeys, "verify_authentication_response", unexpected_verifier)
    session = {
        passkeys.AUTHENTICATION_CHALLENGE_SESSION_KEY: {
            "challenge": "YXV0aGVudGljYXRpb24tY2hhbGxlbmdl",
            "created_at": int(time.time()),
        }
    }

    with pytest.raises(passkeys.PasskeyCeremonyError, match="invalid"):
        passkeys.finish_passkey_authentication(
            session,
            {"id": "aW5hY3RpdmUtY3JlZGVudGlhbA", "response": {}},
        )

    assert verifier_called is False


@PASSKEY_SETTINGS
@pytest.mark.django_db
def test_wrong_origin_or_rp_verification_failure_returns_only_a_generic_error(client, monkeypatch):
    passkeys = importlib.import_module("billing.passkeys")
    credential_model = apps.get_model("billing", "PasskeyCredential")
    user = UserFactory()
    credential_model.objects.create(
        user=user,
        name="Origin protected key",
        credential_id=b"origin-credential",
        public_key=b"origin-public-key",
    )
    session = client.session
    session[passkeys.AUTHENTICATION_CHALLENGE_SESSION_KEY] = {
        "challenge": "YXV0aGVudGljYXRpb24tY2hhbGxlbmdl",
        "created_at": int(time.time()),
    }
    session.save()

    def reject_unexpected_origin(**_kwargs):
        raise InvalidAuthenticationResponse("Unexpected origin")

    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        reject_unexpected_origin,
    )

    response = client.post(
        "/passkeys/authentication/verify/",
        data=json.dumps({"credential": {"id": "b3JpZ2luLWNyZWRlbnRpYWw", "response": {}}}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Anmeldung mit Passkey fehlgeschlagen."}
    assert SESSION_KEY not in client.session


@pytest.mark.django_db
def test_user_can_store_multiple_independently_named_passkeys():
    credential_model = apps.all_models["billing"].get("passkeycredential")
    assert credential_model is not None

    user = UserFactory()
    first = credential_model.objects.create(
        user=user,
        name="MacBook",
        credential_id=b"first-credential",
        public_key=b"first-public-key",
    )
    second = credential_model.objects.create(
        user=user,
        name="Security Key",
        credential_id=b"second-credential",
        public_key=b"second-public-key",
    )

    assert list(user.passkey_credentials.order_by("name").values_list("name", flat=True)) == [
        "MacBook",
        "Security Key",
    ]
    assert first.user_handle == second.user_handle
