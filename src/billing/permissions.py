from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied

ADMIN_GROUP = "Admin"
EDITOR_GROUP = "Bearbeiter"
HUEBERS_GROUP = "Huebers"


def is_admin(user):
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name=ADMIN_GROUP).exists())


def is_editor(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name__in=[ADMIN_GROUP, EDITOR_GROUP]).exists()
    )


def is_huebers(user):
    return user.is_authenticated and user.groups.filter(name=HUEBERS_GROUP).exists()


def is_meal_manager(user):
    return is_editor(user) or is_huebers(user)


def admin_required(view_func):
    return user_passes_test(is_admin)(view_func)


def superuser_required(view_func):
    return user_passes_test(lambda user: user.is_authenticated and user.is_active and user.is_superuser)(view_func)


def editor_required(view_func):
    return user_passes_test(is_editor)(view_func)


def meal_manager_required(view_func):
    return user_passes_test(is_meal_manager)(view_func)


def require_editor(user):
    if not is_editor(user):
        raise PermissionDenied
