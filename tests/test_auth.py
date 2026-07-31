import pytest
from django.contrib.auth import authenticate

from tests.factories import UserFactory


@pytest.mark.django_db
def test_user_can_authenticate_with_email():
    UserFactory(username="ada", email="ada@example.org", password="secret-pass")

    user = authenticate(username="ada@example.org", password="secret-pass")

    assert user is not None
    assert user.username == "ada"


@pytest.mark.django_db
def test_login_rate_limiting_blocks_after_max_attempts(client):
    UserFactory(username="testuser", password="valid-password")

    # Perform 5 failed login attempts
    for _ in range(5):
        response = client.post(
            "/login/",
            {"username": "testuser", "password": "wrong-password"},
        )
        assert response.status_code == 200

    # 6th attempt with valid credentials should be blocked due to rate limiting
    response = client.post(
        "/login/",
        {"username": "testuser", "password": "valid-password"},
    )
    assert response.status_code == 200
    assert "Zu viele Fehlversuche" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_login_rate_limiting_blocks_by_username_across_different_ips(client):
    UserFactory(username="targetuser", password="valid-password")

    # 5 failed attempts across different IP addresses for the same username
    for i in range(5):
        response = client.post(
            "/login/",
            {"username": "targetuser", "password": "wrong-password"},
            REMOTE_ADDR=f"192.168.1.{i + 1}",
        )
        assert response.status_code == 200

    # Next attempt for targetuser from a brand new IP should still be blocked by username rate limit
    response = client.post(
        "/login/",
        {"username": "targetuser", "password": "valid-password"},
        REMOTE_ADDR="10.0.0.99",
    )
    assert response.status_code == 200
    assert "Zu viele Fehlversuche" in response.content.decode("utf-8")
