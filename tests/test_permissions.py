import pytest
from django.contrib.auth.models import Group, User

from billing.permissions import ADMIN_GROUP, EDITOR_GROUP, is_admin, is_editor


@pytest.mark.django_db
def test_admin_group_has_admin_and_editor_access():
    user = User.objects.create_user(username="admin", password="test")
    group = Group.objects.create(name=ADMIN_GROUP)
    user.groups.add(group)

    assert is_admin(user) is True
    assert is_editor(user) is True


@pytest.mark.django_db
def test_editor_group_has_no_admin_access():
    user = User.objects.create_user(username="editor", password="test")
    group = Group.objects.create(name=EDITOR_GROUP)
    user.groups.add(group)

    assert is_admin(user) is False
    assert is_editor(user) is True
