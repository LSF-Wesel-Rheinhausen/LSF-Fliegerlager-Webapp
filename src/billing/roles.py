from django.contrib.auth.models import Group, Permission
from django.db.models import Q

from .permissions import ADMIN_GROUP, EDITOR_GROUP


def bootstrap_default_roles():
    admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP)
    editor_group, _ = Group.objects.get_or_create(name=EDITOR_GROUP)

    admin_group.permissions.set(Permission.objects.all())
    editable = Permission.objects.filter(content_type__app_label="billing").filter(
        Q(codename__startswith="add_") | Q(codename__startswith="change_") | Q(codename__startswith="view_")
    )
    editor_group.permissions.set(editable)

    return admin_group, editor_group
