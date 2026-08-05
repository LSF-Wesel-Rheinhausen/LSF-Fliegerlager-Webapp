import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from billing.models import Expense, ParticipantFamilyMemberPin, ParticipantPin
from billing.roles import bootstrap_default_roles
from tests.factories import CampFactory, GroupFactory, ParticipantFactory, SuperUserFactory, UserFactory


@pytest.fixture
def delegated_user_admin():
    user = UserFactory(username="delegated-admin", is_staff=True, is_superuser=False)
    user.groups.add(GroupFactory(name="Admin"))
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="auth", codename="change_user"),
        Permission.objects.get(content_type__app_label="auth", codename="view_user"),
    )
    return user


@pytest.mark.django_db
def test_app_admin_only_accesses_non_sensitive_billing_models(client):
    admin_group, _editor_group, _huebers_group = bootstrap_default_roles()
    app_admin = UserFactory(username="app-admin", is_staff=True, is_superuser=False)
    app_admin.groups.add(admin_group)
    client.force_login(app_admin)

    assert client.get(reverse("admin:billing_camp_changelist")).status_code == 200
    assert client.get(reverse("admin:auth_user_changelist")).status_code == 403
    assert client.get("/admin/billing/participantpin/").status_code == 404
    assert client.get(reverse("admin:billing_dailysettlementbackupsettings_changelist")).status_code == 403


def test_pin_hash_models_are_not_registered_in_django_admin():
    assert admin.site.is_registered(ParticipantPin) is False
    assert admin.site.is_registered(ParticipantFamilyMemberPin) is False


@pytest.mark.django_db
def test_expense_admin_rejects_spoofed_receipt_content(client):
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp)
    client.force_login(SuperUserFactory())

    response = client.post(
        reverse("admin:billing_expense_add"),
        {
            "camp": camp.pk,
            "participant": participant.pk,
            "category": "Verbrauchsmaterial",
            "description": "Manipulierter Beleg",
            "amount": "12.50",
            "receipt": SimpleUploadedFile(
                "rechnung.pdf",
                b"<script>alert(1)</script>",
                content_type="application/pdf",
            ),
            "status": Expense.Status.PENDING,
            "allocation_method": Expense.AllocationMethod.NONE,
            "_save": "Speichern",
        },
    )

    assert response.status_code == 200
    assert "Dateiinhalt passt nicht zum Dateityp" in response.content.decode()
    assert not Expense.objects.filter(description="Manipulierter Beleg").exists()


@pytest.mark.django_db
def test_non_superuser_user_admin_cannot_assign_privileged_fields(client, delegated_user_admin):
    client.force_login(delegated_user_admin)
    url = reverse("admin:auth_user_change", args=[delegated_user_admin.pk])

    response = client.get(url)

    assert response.status_code == 200
    assert 'name="is_superuser"' not in response.content.decode()
    assert 'name="is_staff"' not in response.content.decode()
    assert 'name="groups"' not in response.content.decode()
    assert 'name="user_permissions"' not in response.content.decode()

    response = client.post(
        url,
        {
            "username": delegated_user_admin.username,
            "first_name": delegated_user_admin.first_name,
            "last_name": delegated_user_admin.last_name,
            "email": delegated_user_admin.email,
            "date_joined_0": delegated_user_admin.date_joined.date().isoformat(),
            "date_joined_1": delegated_user_admin.date_joined.time().strftime("%H:%M:%S"),
            "is_active": "on",
            "is_staff": "on",
            "is_superuser": "on",
            "groups": [],
            "user_permissions": [],
            "_save": "Speichern",
        },
    )

    delegated_user_admin.refresh_from_db()
    assert response.status_code == 302
    assert delegated_user_admin.is_superuser is False
    assert delegated_user_admin.is_staff is True
    assert delegated_user_admin.groups.filter(name="Admin").exists()


@pytest.mark.django_db
def test_non_superuser_user_admin_cannot_change_superuser(client, delegated_user_admin):
    superuser = SuperUserFactory(username="protected-superuser")
    client.force_login(delegated_user_admin)

    change_response = client.get(reverse("admin:auth_user_change", args=[superuser.pk]))
    password_response = client.get(reverse("admin:auth_user_password_change", args=[superuser.pk]))

    assert change_response.status_code == 200
    assert change_response.context["has_change_permission"] is False
    assert '_save"' not in change_response.content.decode()
    assert password_response.status_code == 403


@pytest.mark.django_db
def test_superuser_user_admin_retains_privileged_fields(client):
    superuser = SuperUserFactory(username="root-admin")
    client.force_login(superuser)

    response = client.get(reverse("admin:auth_user_change", args=[superuser.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert 'name="is_superuser"' in content
    assert 'name="is_staff"' in content
    assert 'name="groups"' in content
    assert 'name="user_permissions"' in content
