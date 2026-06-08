import pytest
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.urls import reverse

from billing.models import UserProfile
from billing.permissions import (
    ADMIN_GROUP,
    EDITOR_GROUP,
    HUEBERS_GROUP,
    is_admin,
    is_editor,
    is_huebers,
    is_meal_manager,
)
from tests.factories import GroupFactory, UserFactory


def _admin_user():
    user = UserFactory(username="admin", password="admin-pass")
    user.groups.add(GroupFactory(name=ADMIN_GROUP))
    return user


@pytest.mark.django_db
def test_admin_can_create_admin_user(client):
    client.force_login(_admin_user())

    response = client.post(
        reverse("user-create"),
        {
            "username": "second-admin",
            "first_name": "Second",
            "last_name": "Admin",
            "email": "second-admin@example.test",
            "phone": "+49 281 123456",
            "role": "admin",
            "password1": "strong-test-pass-123",
            "password2": "strong-test-pass-123",
        },
    )

    user = User.objects.get(username="second-admin")
    assert response.status_code == 302
    assert response["Location"] == reverse("user-list")
    assert user.first_name == "Second"
    assert user.last_name == "Admin"
    assert user.email == "second-admin@example.test"
    assert user.profile.phone == "+49 281 123456"
    assert user.is_staff is True
    assert user.is_superuser is False
    assert is_admin(user) is True
    assert is_editor(user) is True


@pytest.mark.django_db
def test_admin_can_create_editor_user(client):
    client.force_login(_admin_user())

    response = client.post(
        reverse("user-create"),
        {
            "username": "editor",
            "email": "editor@example.test",
            "role": "editor",
            "password1": "strong-test-pass-123",
            "password2": "strong-test-pass-123",
        },
    )

    user = User.objects.get(username="editor")
    assert response.status_code == 302
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.groups.filter(name=EDITOR_GROUP).exists()
    assert is_admin(user) is False
    assert is_editor(user) is True


@pytest.mark.django_db
def test_admin_can_create_huebers_user(client):
    client.force_login(_admin_user())

    response = client.post(
        reverse("user-create"),
        {
            "username": "huebers",
            "email": "huebers@example.test",
            "role": "huebers",
            "password1": "strong-test-pass-123",
            "password2": "strong-test-pass-123",
        },
    )

    user = User.objects.get(username="huebers")
    assert response.status_code == 302
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.groups.filter(name=HUEBERS_GROUP).exists()
    assert is_admin(user) is False
    assert is_editor(user) is False
    assert is_huebers(user) is True
    assert is_meal_manager(user) is True


@pytest.mark.django_db
def test_non_admin_cannot_access_user_management(client):
    client.force_login(UserFactory(username="plain-user"))

    response = client.get(reverse("user-list"))

    assert response.status_code == 302
    assert reverse("login") in response["Location"]


@pytest.mark.django_db
def test_admin_can_change_user_role(client):
    client.force_login(_admin_user())
    user = UserFactory(username="role-user", email="role-user@example.test")
    user.groups.add(GroupFactory(name=EDITOR_GROUP))
    UserProfile.objects.create(user=user, phone="alt")

    response = client.post(
        reverse("user-edit", args=[user.pk]),
        {
            "username": "renamed-role-user",
            "first_name": "Rollen",
            "last_name": "Nutzer",
            "email": "role-user-new@example.test",
            "phone": "0123 / 456",
            "role": "admin",
            "is_active": "on",
        },
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.username == "renamed-role-user"
    assert user.first_name == "Rollen"
    assert user.last_name == "Nutzer"
    assert user.email == "role-user-new@example.test"
    assert user.profile.phone == "0123 / 456"
    assert user.groups.filter(name=ADMIN_GROUP).exists()
    assert user.groups.filter(name=EDITOR_GROUP).exists() is False
    assert user.is_staff is True


@pytest.mark.django_db
def test_admin_can_reset_user_password(client):
    client.force_login(_admin_user())
    user = UserFactory(username="needs-reset", password="old-password")

    response = client.post(
        reverse("user-password-reset", args=[user.pk]),
        {"new_password1": "new-strong-pass-123", "new_password2": "new-strong-pass-123"},
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.check_password("new-strong-pass-123") is True


@pytest.mark.django_db
def test_deactivated_user_cannot_authenticate(client):
    client.force_login(_admin_user())
    user = UserFactory(username="inactive-user", email="inactive@example.test", password="old-password")
    user.groups.add(GroupFactory(name=EDITOR_GROUP))

    response = client.post(
        reverse("user-edit", args=[user.pk]),
        {
            "username": "inactive-user",
            "first_name": "",
            "last_name": "",
            "email": "inactive@example.test",
            "phone": "",
            "role": "editor",
        },
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.is_active is False
    assert authenticate(username="inactive@example.test", password="old-password") is None


@pytest.mark.django_db
def test_last_active_admin_cannot_be_deactivated_or_demoted(client):
    admin = _admin_user()
    client.force_login(admin)

    deactivate_response = client.post(
        reverse("user-edit", args=[admin.pk]),
        {
            "username": admin.username,
            "first_name": admin.first_name,
            "last_name": admin.last_name,
            "email": admin.email,
            "phone": "",
            "role": "admin",
        },
    )
    demote_response = client.post(
        reverse("user-edit", args=[admin.pk]),
        {
            "username": admin.username,
            "first_name": admin.first_name,
            "last_name": admin.last_name,
            "email": admin.email,
            "phone": "",
            "role": "editor",
            "is_active": "on",
        },
    )

    admin.refresh_from_db()
    assert deactivate_response.status_code == 200
    assert demote_response.status_code == 200
    assert admin.is_active is True
    assert admin.groups.filter(name=ADMIN_GROUP).exists()
