from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.http import HttpRequest


class AutheliaEmailBackend(ModelBackend):
    """Authenticate an existing active user from Authelia's trusted email header."""

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        authelia_email: str | None = None,
        **_kwargs: Any,
    ) -> Any | None:
        if not settings.AUTHELIA_SSO_ENABLED or authelia_email is None:
            return None

        email = authelia_email.strip()
        try:
            validate_email(email)
        except ValidationError:
            return None

        UserModel = get_user_model()
        try:
            user = UserModel._default_manager.get(email__iexact=email)
        except (UserModel.DoesNotExist, UserModel.MultipleObjectsReturned):
            return None
        return user if self.user_can_authenticate(user) else None

    def get_user(self, user_id: Any) -> Any | None:
        if not settings.AUTHELIA_SSO_ENABLED:
            return None
        return super().get_user(user_id)


class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        login = username or kwargs.get("email")
        if not login or password is None:
            return None
        UserModel = get_user_model()
        try:
            user = UserModel.objects.get(Q(username__iexact=login) | Q(email__iexact=login))
        except UserModel.DoesNotExist:
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
