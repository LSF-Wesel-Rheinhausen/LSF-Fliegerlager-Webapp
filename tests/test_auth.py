import pytest
from django.contrib.auth import authenticate
from django.contrib.auth.models import User


@pytest.mark.django_db
def test_user_can_authenticate_with_email():
    User.objects.create_user(username="ada", email="ada@example.org", password="secret-pass")

    user = authenticate(username="ada@example.org", password="secret-pass")

    assert user is not None
    assert user.username == "ada"
