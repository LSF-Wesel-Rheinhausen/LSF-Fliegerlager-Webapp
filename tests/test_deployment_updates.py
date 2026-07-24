import io
import json
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse

from billing.deployment_updates import UpdateAgentError, agent_request, check_for_update, create_backup_archive
from billing.models import DailySettlementBackupSettings
from billing.permissions import ADMIN_GROUP
from tests.factories import SuperUserFactory, UserFactory


@pytest.fixture
def superuser():
    return SuperUserFactory(username="deployment-admin")


@pytest.fixture
def app_admin():
    user = UserFactory(username="app-admin")
    user.groups.add(Group.objects.create(name=ADMIN_GROUP))
    return user


@pytest.mark.django_db
def test_deployment_page_is_limited_to_superusers(client, superuser, app_admin):
    url = reverse("deployment-update")
    assert client.get(url).status_code == 302

    client.force_login(app_admin)
    assert client.get(url).status_code == 302

    client.force_login(superuser)
    with patch("billing.views.deployment_status", return_value={"phase": "idle", "message": "Bereit"}):
        response = client.get(url)

    assert response.status_code == 200
    assert b"Container-Update" in response.content


@pytest.mark.django_db
def test_update_check_requires_post_and_reports_available_image(client, superuser):
    client.force_login(superuser)
    url = reverse("deployment-update-check")

    assert client.get(url).status_code == 405
    with patch("billing.views.check_for_update", return_value={"update_available": True}):
        response = client.post(url, follow=True)

    assert response.status_code == 200
    assert "Ein neues Container-Image ist verfügbar." in [str(message) for message in response.context["messages"]]


@pytest.mark.django_db
def test_update_install_handles_agent_failure(client, superuser):
    client.force_login(superuser)
    with patch("billing.views.install_update", side_effect=UpdateAgentError("Agent nicht erreichbar")):
        response = client.post(reverse("deployment-update-install"), follow=True)

    assert response.status_code == 200
    assert "Agent nicht erreichbar" in [str(message) for message in response.context["messages"]]


@pytest.mark.django_db
def test_update_install_starts_agent(client, superuser):
    client.force_login(superuser)

    with patch("billing.views.install_update", return_value={"status": "accepted"}) as install:
        response = client.post(reverse("deployment-update-install"), follow=True)

    assert response.status_code == 200
    install.assert_called_once_with()
    assert "Update gestartet. Die Anwendung wird in Kürze neu gestartet." in [
        str(message) for message in response.context["messages"]
    ]


@pytest.mark.django_db
def test_superuser_can_update_daily_backup_settings(client, superuser):
    client.force_login(superuser)
    with patch("billing.views.deployment_status", return_value={"phase": "idle", "message": "Bereit"}):
        response = client.post(
            reverse("deployment-daily-backup-settings"),
            {"enabled": "on", "run_time": "06:15"},
            follow=True,
        )

    backup_settings = DailySettlementBackupSettings.load()
    assert response.status_code == 200
    assert backup_settings.enabled is True
    assert backup_settings.run_time.isoformat(timespec="minutes") == "06:15"


@pytest.mark.django_db
def test_non_superuser_cannot_update_daily_backup_settings(client, app_admin):
    client.force_login(app_admin)

    response = client.post(reverse("deployment-daily-backup-settings"), {"enabled": "on", "run_time": "06:15"})

    assert response.status_code == 302
    assert DailySettlementBackupSettings.load().enabled is False


@override_settings(UPDATE_AGENT_URL="http://updater:8080", UPDATE_AGENT_TOKEN="secret-token")
def test_agent_request_uses_bearer_token_and_parses_json():
    response = Mock()
    response.__enter__ = Mock(return_value=io.BytesIO(json.dumps({"phase": "idle"}).encode()))
    response.__exit__ = Mock(return_value=False)

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = agent_request("/status")

    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer secret-token"
    assert result == {"phase": "idle"}


@override_settings(
    UPDATE_AGENT_URL="http://updater:8080",
    UPDATE_AGENT_TOKEN="secret-token",
    APP_VERSION="1.2.3",
    APP_REVISION="abc123",
    APP_BUILD_DATE="2026-06-09T12:00:00Z",
    APP_CHANGE="feat: deployment updates",
)
def test_check_for_update_sends_current_build_metadata():
    response = Mock()
    response.__enter__ = Mock(return_value=io.BytesIO(json.dumps({"update_available": True}).encode()))
    response.__exit__ = Mock(return_value=False)

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = check_for_update()

    request = urlopen.call_args.args[0]
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode()) == {
        "current": {
            "version": "1.2.3",
            "revision": "abc123",
            "build_date": "2026-06-09T12:00:00Z",
            "change": "feat: deployment updates",
        }
    }
    assert result == {"update_available": True}


@pytest.mark.django_db
def test_deployment_page_renders_update_changelog(client, superuser):
    client.force_login(superuser)
    with patch(
        "billing.views.deployment_status",
        return_value={
            "phase": "checked",
            "message": "Bereit",
            "changelog": [
                {
                    "title": "Kiosk verbessert",
                    "body": "- Schnellbuchung stabilisiert\n- PDF-Vorschau ergänzt",
                }
            ],
        },
    ):
        response = client.get(reverse("deployment-update"))

    assert response.status_code == 200
    assert "Änderungen seit installierter Version" in response.content.decode("utf-8")
    assert "zwischen installierter und verfügbarer Version" in response.content.decode("utf-8")
    assert "Kiosk verbessert" in response.content.decode("utf-8")
    assert "Schnellbuchung stabilisiert" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_deployment_page_renders_update_dialog_script_as_external_asset(client, superuser):
    client.force_login(superuser)

    with patch(
        "billing.views.deployment_status",
        return_value={
            "phase": "checked",
            "message": "Update verfügbar",
            "update_available": True,
            "latest": {"version": "1.2.4", "revision": "newrev", "build_date": "2026-07-08"},
        },
    ):
        response = client.get(reverse("deployment-update"))

    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'data-dialog-open="update-confirmation"' in content
    assert 'action="/deployment/update/install/"' in content
    assert 'data-cfasync="false" defer src="/static/billing/deployment_update.js"' in content
    assert 'document.querySelectorAll("[data-dialog-open]")' not in content


@override_settings(UPDATE_AGENT_URL="http://updater:8080", UPDATE_AGENT_TOKEN="secret-token")
def test_create_backup_archive_sends_staging_payload():
    response = Mock()
    response.__enter__ = Mock(return_value=io.BytesIO(json.dumps({"backup": "daily.tar.gz"}).encode()))
    response.__exit__ = Mock(return_value=False)

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = create_backup_archive("staging/run", "daily-run")

    request = urlopen.call_args.args[0]
    assert request.full_url == "http://updater:8080/backup"
    assert json.loads(request.data.decode()) == {"staging_dir": "staging/run", "archive_prefix": "daily-run"}
    assert result == {"backup": "daily.tar.gz"}


@override_settings(UPDATE_AGENT_URL="", UPDATE_AGENT_TOKEN="")
def test_agent_request_rejects_missing_configuration():
    with pytest.raises(UpdateAgentError, match="nicht konfiguriert"):
        agent_request("/status")


def test_whitenoise_is_configured_for_production_static_files(settings):
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in settings.MIDDLEWARE
    assert settings.STORAGES["staticfiles"]["BACKEND"] in {
        "django.contrib.staticfiles.storage.StaticFilesStorage",
        "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }


@pytest.mark.django_db
def test_deployment_update_status_json_returns_status_for_superuser(client, superuser):
    client.force_login(superuser)
    with patch(
        "billing.views.deployment_status",
        return_value={"phase": "installing", "message": "Wird installiert...", "error": ""},
    ):
        response = client.get(reverse("deployment-update-status-json"))

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"phase": "installing", "message": "Wird installiert...", "error": ""}


@pytest.mark.django_db
def test_deployment_update_status_json_requires_superuser(client, app_admin):
    client.force_login(app_admin)
    response = client.get(reverse("deployment-update-status-json"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_deployment_update_status_json_handles_agent_error(client, superuser):
    client.force_login(superuser)
    with patch("billing.views.deployment_status", side_effect=UpdateAgentError("Agent offline")):
        response = client.get(reverse("deployment-update-status-json"))

    assert response.status_code == 503
    assert response.json() == {"active": False, "phase": "error", "error": "Agent offline"}
