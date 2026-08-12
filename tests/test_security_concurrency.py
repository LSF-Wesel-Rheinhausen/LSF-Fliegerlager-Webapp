from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest
from django.contrib.auth.models import User
from django.db import close_old_connections, connection
from django.test import Client
from django.urls import reverse

from billing.models import FirstAdminBootstrapLock, ParticipantFamilyMember, ParticipantFamilyMemberPin, ParticipantPin
from tests.factories import ParticipantFactory

pytestmark = pytest.mark.django_db(transaction=True)


def _require_postgresql() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Concurrency regression requires PostgreSQL with separate database connections")


def test_first_admin_bootstrap_allows_only_one_winner_across_postgresql_connections(monkeypatch):
    _require_postgresql()
    FirstAdminBootstrapLock.objects.all().delete()
    initial_check_barrier = Barrier(2)
    exists_calls = 0
    exists_lock = Lock()
    real_exists = User.objects.exists

    def synchronized_empty_check() -> bool:
        nonlocal exists_calls
        result = real_exists()
        with exists_lock:
            exists_calls += 1
            call_number = exists_calls
        if call_number <= 2 and not result:
            initial_check_barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(User.objects, "exists", synchronized_empty_check)

    def submit_setup(username: str) -> int:
        close_old_connections()
        try:
            return (
                Client()
                .post(
                    reverse("setup"),
                    {
                        "username": username,
                        "email": f"{username}@example.org",
                        "password1": "strong-test-pass-123",
                        "password2": "strong-test-pass-123",
                    },
                )
                .status_code
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(submit_setup, ("race-admin-a", "race-admin-b")))

    assert statuses == [200, 302]
    assert User.objects.count() == 1
    assert FirstAdminBootstrapLock.objects.filter(pk=1).exists()


@pytest.mark.parametrize("pin_kind", ["participant", "family_member"])
def test_pin_failure_counter_is_atomic_across_postgresql_connections(pin_kind):
    _require_postgresql()
    participant = ParticipantFactory()
    if pin_kind == "participant":
        pin = participant.pin
        pin.set_pin("2468")
        pin.save()
        pin_model = ParticipantPin
    else:
        family_member = ParticipantFamilyMember.objects.create(
            guardian=participant,
            first_name="Kind",
            last_name="Muster",
            role=ParticipantFamilyMember.Role.COMPANION,
        )
        pin, _created = ParticipantFamilyMemberPin.objects.get_or_create(family_member=family_member)
        pin.set_pin("2468")
        pin.save()
        pin_model = ParticipantFamilyMemberPin

    pin_id = pin.pk
    loaded_barrier = Barrier(2)

    def submit_wrong_pin() -> bool:
        close_old_connections()
        try:
            stale_pin = pin_model.objects.get(pk=pin_id)
            loaded_barrier.wait(timeout=10)
            return stale_pin.check_pin("9999")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: submit_wrong_pin(), range(2)))

    pin.refresh_from_db()
    assert results == [False, False]
    assert pin.failed_attempts == 2
