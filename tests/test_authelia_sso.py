import logging

import pytest
from django.contrib.auth import SESSION_KEY, authenticate
from django.contrib.auth.models import Group, User
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import reverse

from billing.permissions import ADMIN_GROUP
from tests.factories import UserFactory

SSO_SETTINGS = override_settings(
    AUTHELIA_SSO_ENABLED=True,
    AUTHELIA_SSO_EMAIL_HEADER="Remote-Email",
)


@SSO_SETTINGS
@pytest.mark.django_db
def test_authelia_sso_logs_in_unique_active_user_case_insensitively(client):
    group = Group.objects.create(name=ADMIN_GROUP)
    user = UserFactory(email="Admin@example.test", is_staff=True)
    user.groups.add(group)

    response = client.get(reverse("camp-list"), headers={"Remote-Email": " admin@EXAMPLE.test "})

    user.refresh_from_db()
    assert response.status_code == 200
    assert client.session[SESSION_KEY] == str(user.pk)
    assert client.session["_auth_user_backend"] == "billing.auth.AutheliaEmailBackend"
    assert user.is_staff is True
    assert user.is_superuser is False
    assert list(user.groups.values_list("name", flat=True)) == [ADMIN_GROUP]


@pytest.mark.django_db
def test_disabled_authelia_sso_ignores_identity_header(client):
    UserFactory(email="admin@example.test")

    response = client.get(reverse("camp-list"), headers={"Remote-Email": "admin@example.test"})

    assert response.status_code == 302
    assert SESSION_KEY not in client.session


@SSO_SETTINGS
@pytest.mark.django_db
def test_missing_authelia_header_does_not_authenticate(client):
    UserFactory(email="admin@example.test")

    response = client.get(reverse("camp-list"))

    assert response.status_code == 302
    assert SESSION_KEY not in client.session


@SSO_SETTINGS
@pytest.mark.django_db
def test_password_login_still_works_without_authelia_header(client):
    user = UserFactory(username="password-admin", email="admin@example.test", password="secret-pass")

    response = client.post(reverse("login"), {"username": user.username, "password": "secret-pass"})

    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)
    assert client.session["_auth_user_backend"] == "billing.auth.EmailOrUsernameBackend"


@override_settings(AUTHELIA_SSO_ENABLED=True, AUTHELIA_SSO_EMAIL_HEADER="X-Forwarded-Email")
@pytest.mark.django_db
def test_authelia_sso_uses_only_configured_header(client):
    user = UserFactory(email="admin@example.test")

    ignored_response = client.get(reverse("camp-list"), headers={"Remote-Email": user.email})
    accepted_response = client.get(reverse("camp-list"), headers={"X-Forwarded-Email": user.email})

    assert ignored_response.status_code == 302
    assert accepted_response.status_code == 200
    assert client.session[SESSION_KEY] == str(user.pk)


@SSO_SETTINGS
@pytest.mark.django_db
@pytest.mark.parametrize("email", ["not-an-email", "", "missing@example.test"])
def test_invalid_or_unknown_authelia_identity_is_rejected_generically(client, email):
    user_count = User.objects.count()

    response = client.get(reverse("camp-list"), headers={"Remote-Email": email})

    assert response.status_code == 403
    assert response.content == b"Single Sign-on konnte nicht verifiziert werden."
    assert User.objects.count() == user_count
    assert SESSION_KEY not in client.session


@SSO_SETTINGS
@pytest.mark.django_db
def test_duplicate_authelia_email_is_rejected(client):
    UserFactory(email="duplicate@example.test")
    UserFactory(email="DUPLICATE@example.test")

    response = client.get(reverse("camp-list"), headers={"Remote-Email": "duplicate@example.test"})

    assert response.status_code == 403
    assert response.content == b"Single Sign-on konnte nicht verifiziert werden."
    assert SESSION_KEY not in client.session


@SSO_SETTINGS
@pytest.mark.django_db
def test_inactive_authelia_user_is_rejected(client):
    UserFactory(email="inactive@example.test", is_active=False)

    response = client.get(reverse("camp-list"), headers={"Remote-Email": "inactive@example.test"})

    assert response.status_code == 403
    assert response.content == b"Single Sign-on konnte nicht verifiziert werden."


@SSO_SETTINGS
@pytest.mark.django_db
def test_authelia_header_switches_existing_session_user(client):
    previous_user = UserFactory(email="previous@example.test")
    authelia_user = UserFactory(email="sso@example.test")
    client.force_login(previous_user, backend="billing.auth.EmailOrUsernameBackend")

    response = client.get(reverse("camp-list"), headers={"Remote-Email": authelia_user.email})

    assert response.status_code == 200
    assert client.session[SESSION_KEY] == str(authelia_user.pk)
    assert client.session["_auth_user_backend"] == "billing.auth.AutheliaEmailBackend"


@SSO_SETTINGS
@pytest.mark.django_db
def test_authelia_identity_header_is_not_logged(client, caplog):
    secret_identity = "private-identity@example.test"

    with caplog.at_level(logging.WARNING):
        response = client.get(reverse("camp-list"), headers={"Remote-Email": secret_identity})

    assert response.status_code == 403
    assert secret_identity not in caplog.text


@override_settings(AUTHELIA_SSO_ENABLED=True, AUTHELIA_SSO_EMAIL_HEADER="invalid header")
@pytest.mark.django_db
def test_invalid_authelia_header_configuration_is_rejected(client):
    with pytest.raises(ImproperlyConfigured, match="AUTHELIA_SSO_EMAIL_HEADER"):
        client.get(reverse("camp-list"))


@SSO_SETTINGS
@pytest.mark.django_db
def test_authelia_backend_rejects_inactive_user_directly():
    UserFactory(email="inactive@example.test", is_active=False)

    assert authenticate(authelia_email="inactive@example.test") is None


def test_authelia_middleware_runs_after_authentication_middleware(settings):
    authentication_index = settings.MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware")
    authelia_index = settings.MIDDLEWARE.index("config.middleware.AutheliaSSOMiddleware")

    assert authentication_index < authelia_index
