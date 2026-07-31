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


@pytest.mark.django_db
def test_login_rate_limiting_username_is_case_insensitive(client):
    UserFactory(username="AliceAdmin", password="valid-password")

    # 5 failed attempts with mixed case username
    for _ in range(5):
        response = client.post(
            "/login/",
            {"username": "AliceAdmin", "password": "wrong-password"},
            REMOTE_ADDR="192.168.1.1",
        )
        assert response.status_code == 200

    # Attempt with lowercase username from a different IP should still be blocked
    response = client.post(
        "/login/",
        {"username": "aliceadmin", "password": "valid-password"},
        REMOTE_ADDR="10.0.0.1",
    )
    assert response.status_code == 200
    assert "Zu viele Fehlversuche" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_login_rate_limiting_different_users_not_blocked(client):
    UserFactory(username="user1", password="valid-password")
    UserFactory(username="user2", password="valid-password")

    # 5 failed attempts for user1 from IP 1
    for _ in range(5):
        client.post(
            "/login/",
            {"username": "user1", "password": "wrong-password"},
            REMOTE_ADDR="192.168.1.10",
        )

    # user2 from IP 2 should NOT be blocked
    response = client.post(
        "/login/",
        {"username": "user2", "password": "valid-password"},
        REMOTE_ADDR="192.168.1.20",
    )
    assert response.status_code == 302
    assert response.url == "/camps/"


@pytest.mark.django_db
def test_login_rate_limiting_resets_after_window_expires(client):
    from datetime import timedelta
    from unittest.mock import patch

    from django.utils import timezone

    UserFactory(username="timeuser", password="valid-password")
    initial_time = timezone.now()

    # 5 failed attempts at initial time
    with patch("billing.kiosk_security.timezone.now", return_value=initial_time):
        for _ in range(5):
            client.post(
                "/login/",
                {"username": "timeuser", "password": "wrong-password"},
            )

    # Fast forward time by 6 minutes (> 300 seconds window)
    future_time = initial_time + timedelta(minutes=6)
    with patch("billing.kiosk_security.timezone.now", return_value=future_time):
        response = client.post(
            "/login/",
            {"username": "timeuser", "password": "valid-password"},
        )
        assert response.status_code == 302
        assert response.url == "/camps/"


@pytest.mark.django_db
def test_successful_login_does_not_increment_failures(client):
    from billing.models import LoginAttempt

    UserFactory(username="validuser", password="valid-password")

    # Perform 4 successful logins
    for _ in range(4):
        response = client.post(
            "/login/",
            {"username": "validuser", "password": "valid-password"},
        )
        assert response.status_code == 302

    # Should not have recorded any failure attempts
    assert LoginAttempt.objects.count() == 0


@pytest.mark.django_db
def test_empty_form_fields_do_not_increment_failures(client):
    from billing.models import LoginAttempt

    UserFactory(username="someuser")

    # Post empty form multiple times
    for _ in range(5):
        response = client.post("/login/", {"username": "", "password": ""})
        assert response.status_code == 200

    # No failure attempts recorded since no authentication was attempted
    assert LoginAttempt.objects.count() == 0


@pytest.mark.django_db
def test_login_rate_limiting_whitespace_normalized(client):
    UserFactory(username="spaceuser", password="valid-password")

    # 5 failed attempts with trailing/leading spaces in username
    for _ in range(5):
        client.post(
            "/login/",
            {"username": "  spaceuser  ", "password": "wrong-password"},
            REMOTE_ADDR="192.168.2.1",
        )

    # Attempt with clean username from another IP should still be blocked
    response = client.post(
        "/login/",
        {"username": "spaceuser", "password": "valid-password"},
        REMOTE_ADDR="10.0.0.50",
    )
    assert response.status_code == 200
    assert "Zu viele Fehlversuche" in response.content.decode("utf-8")
