import pytest
from django.contrib.auth.models import Group, User
from django.contrib.staticfiles import finders
from django.urls import reverse

from billing.permissions import ADMIN_GROUP, EDITOR_GROUP, HUEBERS_GROUP
from tests.factories import UserFactory


@pytest.mark.django_db
def test_login_redirects_to_setup_before_first_user(client):
    response = client.get(reverse("login"))

    assert response.status_code == 302
    assert response["Location"] == reverse("setup")


@pytest.mark.django_db
def test_setup_creates_first_admin_and_logs_in(client):
    response = client.post(
        reverse("setup"),
        {
            "username": "admin",
            "email": "admin@example.org",
            "password1": "strong-test-pass-123",
            "password2": "strong-test-pass-123",
        },
    )

    user = User.objects.get(username="admin")
    assert response.status_code == 302
    assert response["Location"] == reverse("camp-list")
    assert user.email == "admin@example.org"
    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.groups.filter(name=ADMIN_GROUP).exists()
    assert Group.objects.filter(name=EDITOR_GROUP).exists()
    assert Group.objects.filter(name=HUEBERS_GROUP).exists()

    response = client.get(reverse("camp-list"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_root_opens_kiosk_login(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response["Location"] == reverse("kiosk-login")


@pytest.mark.django_db
def test_setup_is_disabled_after_user_exists(client):
    UserFactory(username="existing")

    response = client.get(reverse("setup"))

    assert response.status_code == 302
    assert response["Location"] == reverse("login")


def test_app_stylesheet_is_discoverable_by_staticfiles():
    assert finders.find("billing/app.css")
