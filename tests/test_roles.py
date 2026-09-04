import pytest
from django.contrib.auth.models import Permission

from billing.permissions import ADMIN_GROUP, EDITOR_GROUP
from billing.roles import bootstrap_default_roles

APP_ADMIN_PERMISSION_MODELS = {
    "bookingauditlog",
    "camp",
    "charge",
    "dailyshiftexception",
    "dailyshifttemplate",
    "drinkentry",
    "expense",
    "mealorder",
    "mealplanentry",
    "mealsignup",
    "participant",
    "participantbookinglink",
    "participantfamilymember",
    "payment",
    "pricerule",
    "settlement",
    "settlementrun",
    "shift",
    "shiftassignment",
    "userprofile",
    "shiftauditlog",
}


@pytest.mark.django_db
def test_bootstrap_default_roles_limits_app_admin_permissions_to_business_models():
    admin_group, _editor_group, _huebers_group = bootstrap_default_roles()

    permissions = admin_group.permissions.select_related("content_type")

    assert permissions.exists()
    assert {permission.content_type.app_label for permission in permissions} == {"billing"}
    assert {permission.content_type.model for permission in permissions} == APP_ADMIN_PERMISSION_MODELS


@pytest.mark.django_db
def test_bootstrap_default_roles_keeps_partner_authorizations_read_only():
    admin_group, editor_group, _huebers_group = bootstrap_default_roles()

    for group in (admin_group, editor_group):
        booking_link_permissions = group.permissions.filter(
            content_type__app_label="billing",
            content_type__model="participantbookinglink",
        )
        assert set(booking_link_permissions.values_list("codename", flat=True)) == {"view_participantbookinglink"}


@pytest.mark.django_db
def test_bootstrap_default_roles_removes_previously_granted_auth_permissions():
    admin_group, _editor_group, _huebers_group = bootstrap_default_roles()
    change_user = Permission.objects.get(content_type__app_label="auth", codename="change_user")
    admin_group.permissions.add(change_user)

    bootstrap_default_roles()

    admin_group.refresh_from_db()
    assert admin_group.name == ADMIN_GROUP
    assert admin_group.permissions.filter(pk=change_user.pk).exists() is False


@pytest.mark.django_db
def test_bootstrap_default_roles_grants_shift_audit_view_only():
    admin_group, editor_group, _huebers_group = bootstrap_default_roles()

    assert set(
        admin_group.permissions.filter(content_type__model="shiftauditlog").values_list("codename", flat=True)
    ) == {"view_shiftauditlog"}
    assert set(
        editor_group.permissions.filter(content_type__model="shiftauditlog").values_list("codename", flat=True)
    ) == {"view_shiftauditlog"}
    assert editor_group.name == EDITOR_GROUP
