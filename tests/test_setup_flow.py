import pytest
from django.contrib.auth.models import Group, User
from django.contrib.staticfiles import finders
from django.urls import reverse

from billing.models import FirstAdminBootstrapLock
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
def test_setup_recreates_missing_bootstrap_lock_after_data_reset(client):
    FirstAdminBootstrapLock.objects.all().delete()

    response = client.post(
        reverse("setup"),
        {
            "username": "admin-after-reset",
            "email": "admin-after-reset@example.org",
            "password1": "strong-test-pass-123",
            "password2": "strong-test-pass-123",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("camp-list")
    assert User.objects.filter(username="admin-after-reset", is_superuser=True).exists()
    assert FirstAdminBootstrapLock.objects.filter(pk=1).exists()


@pytest.mark.django_db
def test_setup_form_escapes_rejected_user_input(client):
    response = client.post(
        reverse("setup"),
        {
            "username": '"><script>alert(1)</script>',
            "email": "not-an-email",
            "password1": "strong-test-pass-123",
            "password2": "different-pass-123",
        },
    )
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert '"><script>alert(1)</script>' not in content
    assert "&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in content


@pytest.mark.django_db
def test_root_requires_shared_camp_access(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response["Location"] == "/kiosk/access/?next=%2F"


@pytest.mark.django_db
def test_setup_is_disabled_after_user_exists(client):
    UserFactory(username="existing")

    response = client.get(reverse("setup"))

    assert response.status_code == 302
    assert response["Location"] == reverse("login")


@pytest.mark.django_db
def test_first_admin_setup_rechecks_user_table_inside_bootstrap_transaction(client, monkeypatch):
    real_exists = User.objects.exists
    injected_competing_user = False

    def exists_with_competing_bootstrap() -> bool:
        nonlocal injected_competing_user
        if not injected_competing_user:
            injected_competing_user = True
            User.objects.create_user(username="competing-admin", password="strong-test-pass-123")
            return False
        return real_exists()

    monkeypatch.setattr(User.objects, "exists", exists_with_competing_bootstrap)
    response = client.post(
        reverse("setup"),
        {
            "username": "second-admin",
            "email": "second@example.org",
            "password1": "strong-test-pass-123",
            "password2": "strong-test-pass-123",
        },
    )

    assert response.status_code == 200
    assert User.objects.count() == 1
    assert User.objects.filter(username="second-admin").exists() is False


def test_app_stylesheet_is_discoverable_by_staticfiles():
    assert finders.find("billing/app-v8.css")
