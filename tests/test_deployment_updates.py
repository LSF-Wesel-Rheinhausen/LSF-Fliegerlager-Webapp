import io
import json
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse

from billing.deployment_updates import UpdateAgentError, agent_request
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
