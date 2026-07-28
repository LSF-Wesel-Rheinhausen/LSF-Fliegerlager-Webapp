import pytest
from django.contrib.auth.models import Permission

from billing.permissions import ADMIN_GROUP
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
}


@pytest.mark.django_db
def test_bootstrap_default_roles_limits_app_admin_permissions_to_business_models():
    admin_group, _editor_group, _huebers_group = bootstrap_default_roles()

    permissions = admin_group.permissions.select_related("content_type")

    assert permissions.exists()
    assert {permission.content_type.app_label for permission in permissions} == {"billing"}
    assert {permission.content_type.model for permission in permissions} == APP_ADMIN_PERMISSION_MODELS


@pytest.mark.django_db
def test_bootstrap_default_roles_removes_previously_granted_auth_permissions():
    admin_group, _editor_group, _huebers_group = bootstrap_default_roles()
    change_user = Permission.objects.get(content_type__app_label="auth", codename="change_user")
    admin_group.permissions.add(change_user)

    bootstrap_default_roles()

    admin_group.refresh_from_db()
    assert admin_group.name == ADMIN_GROUP
    assert admin_group.permissions.filter(pk=change_user.pk).exists() is False
