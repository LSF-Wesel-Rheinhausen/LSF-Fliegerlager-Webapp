from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.test import override_settings


@pytest.mark.django_db
@override_settings(WEB_PUSH_ENABLED=True)
@patch("billing.management.commands.run_push_worker.send_due_push_messages")
@patch("billing.management.commands.run_push_worker.generate_scheduled_notifications")
def test_run_push_worker_generates_and_sends_once(generate, send):
    output = StringIO()

    call_command("run_push_worker", stdout=output)

    generate.assert_called_once_with()
    send.assert_called_once_with()
    assert "Push-Durchlauf abgeschlossen" in output.getvalue()


def test_generate_webpush_keys_outputs_environment_values():
    output = StringIO()

    call_command("generate_webpush_keys", stdout=output)

    values = dict(line.split("=", 1) for line in output.getvalue().strip().splitlines())
    assert len(values["WEB_PUSH_VAPID_PUBLIC_KEY"]) > 40
    assert len(values["WEB_PUSH_VAPID_PRIVATE_KEY"]) > 30
