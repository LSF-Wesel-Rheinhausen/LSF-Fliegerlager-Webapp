import json
import os
import subprocess
import sys

import pytest
from django.contrib.auth import authenticate
from django.core.management import CommandError, call_command
from scripts import local_demo


def test_fixture_is_a_public_allowlisted_django_fixture():
    records = json.loads(local_demo.FIXTURE_PATH.read_text())
    forbidden = {"auth.session", "billing.passkeycredential", "billing.pushsubscription"}

    assert records
    assert all(record["model"] not in forbidden for record in records)
    assert all(record["model"].startswith("billing.") or record["model"] == "auth.user" for record in records)
    assert all("@example.test" in record["fields"]["email"] for record in records if record["fields"].get("email"))
    assert not any(record["model"] in local_demo.FORBIDDEN_MODELS for record in records)
    assert all(record["fields"].get("password") == "!" for record in records if record["model"] == "auth.user")
    assert all(not record["fields"].get("pin_hash") for record in records if record["model"].endswith("pin"))


@pytest.mark.parametrize("payload", ["{}", '[{"model":"unknown.model","pk":1,"fields":{}}]', "[broken"])
def test_fixture_validation_fails_closed(payload, tmp_path, monkeypatch):
    path = tmp_path / "fixture.json"
    path.write_text(payload)
    monkeypatch.setattr(local_demo, "FIXTURE_PATH", path)

    with pytest.raises(CommandError):
        local_demo.read_fixture()


def test_create_rejects_bad_fixture_before_creating_database(tmp_path, monkeypatch):
    fixture = tmp_path / "bad.json"
    fixture.write_text('[{"model":"unknown.model","pk":1,"fields":{}}]')
    database = tmp_path / "must-not-exist.sqlite3"
    monkeypatch.setattr(local_demo, "FIXTURE_PATH", fixture)
    monkeypatch.setattr(sys, "argv", ["local_demo.py", "create", "--database", str(database)])

    with pytest.raises(CommandError):
        local_demo.main()
    assert not database.exists()


def test_create_refuses_existing_or_symlink_target(tmp_path):
    database = tmp_path / "demo.sqlite3"
    database.write_text("keep me")
    with pytest.raises(CommandError):
        local_demo.ensure_new_database(database)
    assert database.read_text() == "keep me"

    database.unlink()
    target = tmp_path / "target.sqlite3"
    target.touch()
    database.symlink_to(target)
    with pytest.raises(CommandError):
        local_demo.ensure_new_database(database)
    assert target.exists()


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_publish_does_not_replace_a_target_created_during_build(tmp_path, kind):
    staging = tmp_path / "complete.sqlite3"
    staging.write_bytes(b"complete database")
    target = tmp_path / "local-demo.sqlite3"
    original = tmp_path / "original.sqlite3"
    original.write_bytes(b"keep")
    if kind == "file":
        target.write_bytes(b"concurrent database")
    else:
        target.symlink_to(original)

    with pytest.raises(CommandError):
        local_demo.publish_database(staging, target)
    if kind == "file":
        assert target.read_bytes() == b"concurrent database"
    else:
        assert target.is_symlink()
        assert original.read_bytes() == b"keep"


def test_failed_create_cleans_staging_and_leaves_target_retryable(tmp_path, monkeypatch):
    database = tmp_path / "local-demo.sqlite3"
    monkeypatch.setattr(local_demo, "_manage", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fail")))
    monkeypatch.setattr(sys, "argv", ["local_demo.py", "create", "--database", str(database)])

    with pytest.raises(RuntimeError, match="fail"):
        local_demo.main()
    assert not database.exists()
    assert not list(tmp_path.glob(".local-demo-*"))
    local_demo.ensure_new_database(database)


@pytest.mark.django_db
def test_restored_fixture_keeps_seeded_user_and_pin_credentials():
    from billing.management.commands.seed_local_test_db import ADMIN_PASSWORD, EDITOR_PASSWORD, SHARED_KIOSK_PIN
    from billing.models import (
        AttendanceDay,
        Camp,
        CampKioskAccess,
        ParticipantBookingLink,
        ParticipantFamilyMemberPin,
        ParticipantPin,
    )
    from billing.roles import ROLE_ADMIN, ROLE_EDITOR, user_role

    call_command("seed_local_test_db", verbosity=0)
    credentials = local_demo.capture_credentials()
    call_command("loaddata", str(local_demo.FIXTURE_PATH), verbosity=0)
    local_demo.restore_credentials(credentials)

    admin = authenticate(username="local-admin", password=ADMIN_PASSWORD)
    editor = authenticate(username="local-editor", password=EDITOR_PASSWORD)
    assert admin is not None and user_role(admin) == ROLE_ADMIN
    assert editor is not None and user_role(editor) == ROLE_EDITOR
    camp = Camp.objects.get(is_active=True)
    assert CampKioskAccess.objects.get(camp=camp).check_pin(SHARED_KIOSK_PIN)
    adult_pin = ParticipantPin.objects.get(participant__first_name="AdultComplete")
    companion_pin = ParticipantFamilyMemberPin.objects.get(family_member__first_name="FamilyCompanion")
    assert adult_pin.pin_hash == credentials["participant_pins"][(camp.name, "AdultComplete", "Synthetic")]
    assert (
        companion_pin.pin_hash
        == credentials["family_pins"][(camp.name, "AdultComplete", "FamilyCompanion", "Synthetic")]
    )
    assert ParticipantBookingLink.objects.filter(status="accepted").exists()
    assert AttendanceDay.objects.filter(participant__first_name="AdultComplete", family_member__isnull=False).exists()


def test_create_round_trip_is_portable_and_rebases_business_dates(tmp_path):
    database = tmp_path / "nested" / "local-demo.sqlite3"
    script = local_demo.ROOT / "scripts" / "local_demo.py"
    subprocess.run(
        [sys.executable, str(script), "create", "--database", str(database), "--reference-date", "2026-11-04"],
        cwd=local_demo.ROOT,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )
    verified = subprocess.run(
        [sys.executable, str(script), "verify", "--database", str(database)],
        cwd=local_demo.ROOT,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )
    assert "OK: 3 Lager, 6 Teilnehmende, 32 Dienste" in verified.stdout
    assert database.stat().st_mode & 0o777 == 0o600
    assert not list(database.parent.glob(".local-demo-*"))
    query = """import json; import django; django.setup()
from django.contrib.auth import get_user_model
from billing import models as m
c=m.Camp.objects.get(is_active=True)
print(json.dumps({
 'start': str(c.starts_on), 'end': str(c.ends_on), 'camps': m.Camp.objects.count(),
 'users': get_user_model().objects.count(), 'participants': m.Participant.objects.count(),
 'family': m.ParticipantFamilyMember.objects.filter(guardian__camp=c).count(),
 'attendance': m.AttendanceDay.objects.filter(participant__camp=c).count(),
 'prices': m.PriceRule.objects.filter(camp=c).count(),
 'charges': m.Charge.objects.filter(participant__camp=c).count(),
 'payments': m.Payment.objects.filter(participant__camp=c).count(),
 'expenses': m.Expense.objects.filter(camp=c).count(),
 'meals': m.MealSignup.objects.filter(participant__camp=c).count(),
 'runs': m.SettlementRun.objects.filter(camp=c).count(),
 'settlements': m.Settlement.objects.filter(run__camp=c).count(),
 'shifts': m.Shift.objects.filter(camp=c).count(),
 'assignments': m.ShiftAssignment.objects.filter(shift__camp=c).count(),
 'templates': m.DailyShiftTemplate.objects.filter(camp=c).count(),
 'exceptions': m.DailyShiftException.objects.filter(template__camp=c).count(),
 'announcements': m.CampAnnouncement.objects.filter(camp=c).count(),
 'drinks': m.DrinkEntry.objects.filter(participant__camp=c).count(),
 'nights': list(m.Participant.objects.filter(camp=c, first_name='AdultComplete')
                .values_list('booked_nights', 'actual_nights'))
}))"""
    result = subprocess.run(
        [sys.executable, "-c", query],
        cwd=local_demo.ROOT,
        env={
            **os.environ,
            "DATABASE_URL": f"sqlite:///{database}",
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "PYTHONPATH": str(local_demo.ROOT / "src"),
        },
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    assert data == {
        "start": "2026-11-01",
        "end": "2026-11-11",
        "camps": 3,
        "users": 4,
        "participants": 6,
        "family": 3,
        "attendance": 8,
        "prices": 7,
        "charges": 7,
        "payments": 3,
        "expenses": 6,
        "meals": 3,
        "runs": 2,
        "settlements": 2,
        "shifts": 32,
        "assignments": 3,
        "templates": 3,
        "exceptions": 1,
        "announcements": 2,
        "drinks": 2,
        "nights": [[10, 3]],
    }


def test_local_environment_disables_external_services(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://remote.invalid/db")
    monkeypatch.setenv("AUTHELIA_SSO_ENABLED", "1")
    monkeypatch.setenv("PASSKEY_ENABLED", "1")
    environment = local_demo.local_environment("/tmp/demo.sqlite3", 8000)

    assert environment["DATABASE_URL"] == f"sqlite:///{local_demo.Path('/tmp/demo.sqlite3').resolve()}"
    assert environment["DJANGO_DEBUG"] == "1"
    assert environment["DJANGO_HTTPS"] == "0"
    assert environment["WEB_PUSH_ENABLED"] == "0"
    assert environment["AUTHELIA_SSO_ENABLED"] == "0"
    assert environment["PASSKEY_ENABLED"] == "0"
    assert environment["UPDATE_AGENT_URL"] == ""
    assert environment["UPDATE_AGENT_TOKEN"] == ""
    assert environment["DATABASE_URL"] != "postgres://remote.invalid/db"
    assert environment["EMAIL_BACKEND"] == "django.core.mail.backends.dummy.EmailBackend"
    assert environment["ACCOUNT_RECOVERY_PUBLIC_ORIGIN"] == "http://localhost:8000"
