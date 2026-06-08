import pytest

from billing.permissions import ADMIN_GROUP, EDITOR_GROUP, is_admin, is_editor
from tests.factories import GroupFactory, UserFactory


@pytest.mark.django_db
def test_admin_group_has_admin_and_editor_access():
    user = UserFactory(username="admin")
    group = GroupFactory(name=ADMIN_GROUP)
    user.groups.add(group)

    assert is_admin(user) is True
    assert is_editor(user) is True


@pytest.mark.django_db
def test_editor_group_has_no_admin_access():
    user = UserFactory(username="editor")
    group = GroupFactory(name=EDITOR_GROUP)
    user.groups.add(group)

    assert is_admin(user) is False
    assert is_editor(user) is True
