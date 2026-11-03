"""Create, verify, or serve the fixed synthetic local demo database."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import date, timedelta
from pathlib import Path

from django.core.management.base import CommandError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "local_demo.json"
REFERENCE_DATE = date(2026, 11, 3)
EXPECTED_COUNTS = {
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
}
ALLOWED_MODELS = {
    "auth.user",
    "billing.camp",
    "billing.userprofile",
    "billing.participant",
    "billing.participantfamilymember",
    "billing.participantbookinglink",
    "billing.attendanceday",
    "billing.pricerule",
    "billing.charge",
    "billing.payment",
    "billing.expense",
    "billing.expenseallocation",
    "billing.mealsignup",
    "billing.mealorder",
    "billing.mealbookingoverride",
    "billing.mealplanentry",
    "billing.drinkentry",
    "billing.settlementrun",
    "billing.settlement",
    "billing.dailyshifttemplate",
    "billing.dailyshiftexception",
    "billing.shift",
    "billing.shiftassignment",
    "billing.campannouncement",
}
FORBIDDEN_MODELS = {
    "auth.session",
    "billing.campkioskaccess",
    "billing.passkeycredential",
    "billing.pushsubscription",
    "billing.pushmessage",
    "billing.emaildelivery",
    "billing.emailbatch",
    "billing.emailtestlog",
    "billing.accountrecoverytoken",
    "billing.accountrecoveryattempt",
    "billing.accountrecoveryidentifierattempt",
    "billing.accountrecoverydeliveryrequest",
    "billing.loginattempt",
    "billing.kioskaccessattempt",
    "billing.kioskregistrationattempt",
    "billing.bookingauditlog",
    "billing.kioskactionauditlog",
    "billing.paymentauditlog",
    "billing.shiftauditlog",
    "billing.dailysettlementbackuplog",
}


def read_fixture() -> list[dict]:
    """Load and validate the fixed, public, synthetic Django fixture."""
    try:
        records = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        if not isinstance(records, list) or not records:
            raise ValueError("fixture must be a non-empty list")
        usernames = set()
        participants = {}
        family_members = {}
        for record in records:
            if not isinstance(record, dict) or record.get("model") not in ALLOWED_MODELS:
                raise ValueError("fixture contains an unsupported model")
            fields = record.get("fields")
            if not isinstance(fields, dict):
                raise ValueError("fixture record is malformed")
            if record["model"] in FORBIDDEN_MODELS:
                raise ValueError("fixture contains sensitive runtime data")
            if record["model"] == "auth.user":
                expected_emails = {
                    "local-admin": "local-admin@example.test",
                    "local-editor": "local-editor@example.test",
                    "local-huebers": "local-huebers@example.test",
                    "local-inactive": "local-inactive@example.test",
                }
                username = fields.get("username")
                if fields.get("password") != "!" or fields.get("email") != expected_emails.get(username):
                    raise ValueError("fixture user is not a public synthetic profile")
                usernames.add(username)
            if record["model"] == "billing.participant":
                participants[(fields.get("first_name"), fields.get("last_name"))] = (
                    fields.get("email", ""),
                    fields.get("phone", ""),
                    fields.get("notes", ""),
                )
            if record["model"] == "billing.participantfamilymember":
                family_members[(fields.get("first_name"), fields.get("last_name"))] = (
                    fields.get("email", ""),
                    fields.get("phone", ""),
                )
            if any(fields.get(key) for key in ("secret", "token", "private_key", "pin_hash", "password_encrypted")):
                raise ValueError("fixture contains credential material")
            if fields.get("receipt"):
                raise ValueError("fixture contains an uploaded receipt path")
        if usernames != {"local-admin", "local-editor", "local-huebers", "local-inactive"}:
            raise ValueError("fixture user allowlist is incomplete")
        expected_participants = {
            ("Anmeldung", "Demo"): ("anmeldung@example.test", "", ""),
            ("AdultComplete", "Synthetic"): ("adultcomplete@example.test", "+49 000 1001", ""),
            ("ArchivedSettled", "Synthetic"): ("archivedsettled@example.test", "", ""),
            ("ChildPartial", "Synthetic"): ("childpartial@example.test", "", ""),
            ("InfantNoDob", "Synthetic"): ("infantnodob@example.test", "", ""),
            ("MissingDob", "Synthetic"): ("", "", ""),
        }
        expected_family = {
            ("FamilyChild", "Synthetic"): ("familychild@example.test", ""),
            ("FamilyCompanion", "Synthetic"): ("familycompanion@example.test", "+49 000 1002"),
            ("InactiveFamily", "Synthetic"): ("", ""),
        }
        if participants != expected_participants or family_members != expected_family:
            raise ValueError("fixture contains an unknown participant or family profile")
        return records
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise CommandError(f"Ungültiges lokales Demo-Fixture: {error}") from error


def ensure_new_database(database: Path) -> None:
    """Refuse existing files and symlinks without touching the destination."""
    if database.is_symlink() or database.exists():
        raise CommandError(f"Datenbank existiert bereits; wird nicht überschrieben: {database}")


def publish_database(staging: Path, database: Path) -> None:
    """Publish a completed database atomically without replacing a racing target."""
    os.chmod(staging, 0o600)
    try:
        os.link(staging, database)
    except FileExistsError as error:
        raise CommandError(f"Datenbank wurde parallel angelegt; wird nicht überschrieben: {database}") from error


def _assert_demo_profile() -> dict[str, int]:
    """Fail unless the loaded database matches the fixed synthetic profile."""
    from django.contrib.auth import get_user_model

    from billing.models import (
        AttendanceDay,
        Camp,
        CampAnnouncement,
        Charge,
        DailyShiftException,
        DailyShiftTemplate,
        DrinkEntry,
        Expense,
        MealSignup,
        Participant,
        ParticipantFamilyMember,
        Payment,
        PriceRule,
        Settlement,
        SettlementRun,
        Shift,
        ShiftAssignment,
    )

    try:
        camp = Camp.objects.get(is_active=True)
    except Camp.DoesNotExist as error:
        raise CommandError("Demo-Datenbank enthält kein aktives Lager.") from error
    counts = {
        "camps": Camp.objects.count(),
        "users": get_user_model().objects.count(),
        "participants": Participant.objects.count(),
        "family": ParticipantFamilyMember.objects.filter(guardian__camp=camp).count(),
        "attendance": AttendanceDay.objects.filter(participant__camp=camp).count(),
        "prices": PriceRule.objects.filter(camp=camp).count(),
        "charges": Charge.objects.filter(participant__camp=camp).count(),
        "payments": Payment.objects.filter(participant__camp=camp).count(),
        "expenses": Expense.objects.filter(camp=camp).count(),
        "meals": MealSignup.objects.filter(participant__camp=camp).count(),
        "runs": SettlementRun.objects.filter(camp=camp).count(),
        "settlements": Settlement.objects.filter(run__camp=camp).count(),
        "shifts": Shift.objects.filter(camp=camp).count(),
        "assignments": ShiftAssignment.objects.filter(shift__camp=camp).count(),
        "templates": DailyShiftTemplate.objects.filter(camp=camp).count(),
        "exceptions": DailyShiftException.objects.filter(template__camp=camp).count(),
        "announcements": CampAnnouncement.objects.filter(camp=camp).count(),
        "drinks": DrinkEntry.objects.filter(participant__camp=camp).count(),
    }
    if counts != EXPECTED_COUNTS:
        raise CommandError(f"Demo-Datenbank hat unerwartete Beispieldaten: {counts}")
    return counts


def local_environment(database: str | Path, port: int) -> dict[str, str]:
    """Return a process environment pinned to local SQLite and disabled integrations."""
    path = Path(database).expanduser().resolve()
    return {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{path}",
        "DJANGO_DEBUG": "1",
        "DJANGO_HTTPS": "0",
        "AUTHELIA_SSO_ENABLED": "0",
        "PASSKEY_ENABLED": "0",
        "WEB_PUSH_ENABLED": "0",
        "UPDATE_AGENT_URL": "",
        "UPDATE_AGENT_TOKEN": "",
        "ACCOUNT_RECOVERY_PUBLIC_ORIGIN": f"http://localhost:{port}",
        "EMAIL_BACKEND": "django.core.mail.backends.dummy.EmailBackend",
    }


def _manage(args: list[str], env: dict[str, str]) -> None:
    subprocess.run([sys.executable, str(ROOT / "src" / "manage.py"), *args], cwd=ROOT, env=env, check=True)


def _django_setup(env: dict[str, str]) -> None:
    os.environ.update(env)
    sys.path.insert(0, str(ROOT / "src"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def shift_dates(offset: int, reference_date: date) -> None:
    """Shift business dates by a day offset; preserve participant birth dates."""
    from billing import models as m

    camp = m.Camp.objects.get(is_active=True)
    date_fields = (
        (m.Camp.objects.filter(pk=camp.pk), ("starts_on", "ends_on")),
        (m.Participant.objects.filter(camp=camp), ("arrival_date", "departure_date")),
        (m.ParticipantFamilyMember.objects.filter(guardian__camp=camp), ("arrival_date", "departure_date")),
        (m.AttendanceDay.objects.filter(participant__camp=camp), ("date",)),
        (m.MealPlanEntry.objects.filter(camp=camp), ("meal_date",)),
        (m.MealOrder.objects.filter(camp=camp), ("meal_date",)),
        (m.MealBookingOverride.objects.filter(camp=camp), ("meal_date",)),
        (m.MealSignup.objects.filter(participant__camp=camp), ("meal_date",)),
        (m.PriceRule.objects.filter(camp=camp), ("meal_date",)),
        (m.Charge.objects.filter(participant__camp=camp), ("occurred_on",)),
        (m.Payment.objects.filter(participant__camp=camp), ("paid_on",)),
        (m.Expense.objects.filter(camp=camp), ("paid_on",)),
        (m.DailyShiftException.objects.filter(template__camp=camp), ("date",)),
        (m.Shift.objects.filter(camp=camp), ("date",)),
    )
    staged_updates = []
    for queryset, fields in date_fields:
        for row in queryset:
            updates = {}
            for name in fields:
                value = getattr(row, name)
                if value is not None:
                    updates[name] = value + timedelta(days=offset)
            if updates:
                staged_updates.append((queryset, row.pk, updates))
    for queryset, primary_key, updates in staged_updates:
        queryset.filter(pk=primary_key).update(
            **{name: value + timedelta(days=5000) for name, value in updates.items()}
        )
    for queryset, primary_key, updates in staged_updates:
        queryset.filter(pk=primary_key).update(**updates)
    for person in m.Participant.objects.filter(camp=camp):
        if person.arrival_date and person.departure_date:
            person.booked_nights = max(0, (person.departure_date - person.arrival_date).days)
            person.actual_nights = max(0, (min(reference_date, person.departure_date) - person.arrival_date).days)
            person.save(update_fields=["booked_nights", "actual_nights"])


def capture_credentials() -> dict[str, dict]:
    """Capture only locally generated credential hashes from the trusted seed."""
    from django.contrib.auth import get_user_model

    from billing.models import CampKioskAccess, ParticipantFamilyMemberPin, ParticipantPin

    users = {user.username: user.password for user in get_user_model().objects.all()}
    kiosks = {
        (access.camp.name, access.camp.year): access.pin_hash
        for access in CampKioskAccess.objects.select_related("camp")
    }
    participant_pins = {
        (pin.participant.camp.name, pin.participant.first_name, pin.participant.last_name): pin.pin_hash
        for pin in ParticipantPin.objects.select_related("participant__camp")
    }
    family_pins = {
        (
            pin.family_member.guardian.camp.name,
            pin.family_member.guardian.first_name,
            pin.family_member.first_name,
            pin.family_member.last_name,
        ): pin.pin_hash
        for pin in ParticipantFamilyMemberPin.objects.select_related("family_member__guardian__camp")
    }
    return {"users": users, "kiosks": kiosks, "participant_pins": participant_pins, "family_pins": family_pins}


def restore_credentials(credentials: dict[str, dict]) -> None:
    """Restore trusted seed hashes after fixture data replaces the seed rows."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from billing.models import (
        CampKioskAccess,
        ParticipantFamilyMemberPin,
        ParticipantPin,
    )
    from billing.roles import ROLE_ADMIN, ROLE_EDITOR, ROLE_HUEBERS, set_user_role

    User = get_user_model()
    for username, password_hash in credentials["users"].items():
        user = User.objects.get(username=username)
        user.password = password_hash
        user.save(update_fields=["password"])
    users = {user.username: user for user in User.objects.all()}
    for username, role in (
        ("local-admin", ROLE_ADMIN),
        ("local-editor", ROLE_EDITOR),
        ("local-huebers", ROLE_HUEBERS),
        ("local-inactive", ROLE_EDITOR),
    ):
        set_user_role(users[username], role)
    for (camp_name, year), pin_hash in credentials["kiosks"].items():
        access = CampKioskAccess.objects.get(camp__name=camp_name, camp__year=year)
        access.pin_hash = pin_hash
        access.generation = uuid.uuid4()
        access.rotated_at = timezone.now()
        access.changed_by = users["local-admin"]
        access.save(update_fields=["pin_hash", "generation", "rotated_at", "changed_by", "updated_at"])
    for key, pin_hash in credentials["participant_pins"].items():
        camp_name, first_name, last_name = key
        ParticipantPin.objects.filter(
            participant__camp__name=camp_name,
            participant__first_name=first_name,
            participant__last_name=last_name,
        ).update(pin_hash=pin_hash)
    for key, pin_hash in credentials["family_pins"].items():
        camp_name, guardian_name, member_name, member_last_name = key
        ParticipantFamilyMemberPin.objects.filter(
            family_member__guardian__camp__name=camp_name,
            family_member__guardian__first_name=guardian_name,
            family_member__first_name=member_name,
            family_member__last_name=member_last_name,
        ).update(pin_hash=pin_hash)
    from billing.models import DailySettlementBackupSettings, EmailConfiguration

    configuration = EmailConfiguration.load()
    configuration.enabled = False
    configuration.host = ""
    configuration.username = ""
    configuration.password_encrypted = ""
    configuration.save(update_fields=["enabled", "host", "username", "password_encrypted"])
    backups = DailySettlementBackupSettings.load()
    backups.enabled = False
    backups.save(update_fields=["enabled"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("create", "verify", "serve"):
        child = subparsers.add_parser(action)
        child.add_argument("--database", type=Path, default=ROOT / "data" / "local-demo.sqlite3")
        child.add_argument("--reference-date", type=date.fromisoformat, default=date.today())
        if action == "serve":
            child.add_argument("--port", type=int, default=8000)
    options = parser.parse_args()
    database = options.database.expanduser().absolute()
    port = getattr(options, "port", 8000)
    env = local_environment(database, port)
    if options.action == "create":
        read_fixture()
        ensure_new_database(database)
        database.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".local-demo-", dir=database.parent) as work_dir:
            staging = Path(work_dir) / database.name
            staging_env = local_environment(staging, port)
            connections = None
            try:
                _manage(["migrate", "--noinput"], staging_env)
                _django_setup(staging_env)
                from django.core.management import call_command
                from django.db import connections as django_connections

                connections = django_connections
                call_command("seed_local_test_db", verbosity=0)
                credentials = capture_credentials()
                connections.close_all()
                _manage(["loaddata", str(FIXTURE_PATH)], staging_env)
                _django_setup(staging_env)
                restore_credentials(credentials)
                shift_dates((options.reference_date - REFERENCE_DATE).days, options.reference_date)
                _assert_demo_profile()
                connections.close_all()
                publish_database(staging, database)
            finally:
                if connections is not None:
                    connections.close_all()
    elif options.action == "verify":
        if database.is_symlink() or not database.is_file():
            raise CommandError(f"Datenbank fehlt oder ist ein Symlink: {database}")
        with sqlite3.connect(database) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "billing_camp" not in tables:
                raise CommandError("Keine gültige Demo-Datenbank.")
        _django_setup(env)
        actual_counts = _assert_demo_profile()
        if actual_counts != EXPECTED_COUNTS:
            raise CommandError(f"Demo-Datenbank hat unerwartete Beispieldaten: {actual_counts}")
        print(
            f"OK: {actual_counts['camps']} Lager, {actual_counts['participants']} Teilnehmende, "
            f"{actual_counts['shifts']} Dienste"
        )
    else:
        if not database.is_file() or database.is_symlink():
            raise CommandError("Demo-Datenbank fehlt; zuerst create ausführen.")
        _django_setup(env)
        from django.core.management import call_command

        call_command("runserver", f"127.0.0.1:{port}", use_reloader=False, insecure=True)


if __name__ == "__main__":
    main()
