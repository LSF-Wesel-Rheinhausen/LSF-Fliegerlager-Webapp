from typing import Any

from django.contrib.auth.models import Group, Permission
from django.db.models import Q

from .permissions import ADMIN_GROUP, EDITOR_GROUP

ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_CHOICES = (
    (ROLE_ADMIN, "Admin"),
    (ROLE_EDITOR, "Bearbeiter"),
)


def bootstrap_default_roles():
    admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP)
    editor_group, _ = Group.objects.get_or_create(name=EDITOR_GROUP)

    admin_group.permissions.set(Permission.objects.all())
    editable = Permission.objects.filter(content_type__app_label="billing").filter(
        Q(codename__startswith="add_") | Q(codename__startswith="change_") | Q(codename__startswith="view_")
    )
    editor_group.permissions.set(editable)

    return admin_group, editor_group


def set_user_role(user: Any, role: str) -> None:
    """Assign the application role groups and staff flag for a user.

    Args:
        user: Django user instance to update.
        role: One of ``ROLE_ADMIN`` or ``ROLE_EDITOR``.

    Raises:
        ValueError: If ``role`` is not a supported application role.
    """
    admin_group, editor_group = bootstrap_default_roles()
    user.groups.remove(admin_group, editor_group)
    if role == ROLE_ADMIN:
        user.groups.add(admin_group)
        user.is_staff = True
    elif role == ROLE_EDITOR:
        user.groups.add(editor_group)
        user.is_staff = False
    else:
        raise ValueError(f"Unsupported role: {role}")
    user.save(update_fields=["is_staff"])


def user_role(user: Any) -> str:
    """Return the effective editable application role for a user."""
    if user.is_superuser or user.groups.filter(name=ADMIN_GROUP).exists():
        return ROLE_ADMIN
    if user.groups.filter(name=EDITOR_GROUP).exists():
        return ROLE_EDITOR
    return ROLE_EDITOR


def active_admin_count(user_model: Any, exclude_user: Any | None = None) -> int:
    """Count active users that still satisfy the application admin contract."""
    queryset = user_model.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(groups__name=ADMIN_GROUP))
    if exclude_user is not None and exclude_user.pk:
        queryset = queryset.exclude(pk=exclude_user.pk)
    return queryset.distinct().count()
