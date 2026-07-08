import json
from datetime import datetime, time
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from billing.daily_settlement_backups import build_settlement_backup_staging, run_due_daily_settlement_backup
from billing.deployment_updates import UpdateAgentError
from billing.models import Camp, DailySettlementBackupLog, DailySettlementBackupSettings, SettlementRun
from billing.services import create_settlement_run
from tests.factories import ChargeFactory, ParticipantFactory, SuperUserFactory


@pytest.mark.django_db
def test_daily_backup_does_not_run_before_configured_time():
    DailySettlementBackupSettings.objects.create(enabled=True, run_time=time(5, 0))
    ParticipantFactory()
    now = timezone.make_aware(datetime(2026, 7, 7, 4, 59))

    result = run_due_daily_settlement_backup(now=now)

    assert result is None
    assert SettlementRun.objects.count() == 0
    assert DailySettlementBackupLog.objects.count() == 0


@pytest.mark.django_db
def test_daily_backup_creates_one_daily_backup_run(settings, tmp_path):
    settings.BACKUP_DIR = tmp_path
    DailySettlementBackupSettings.objects.create(enabled=True, run_time=time(5, 0))
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    ChargeFactory(participant=participant, unit_price=Decimal("12.00"))
    now = timezone.make_aware(datetime(2026, 7, 7, 5, 0))

    with patch("billing.daily_settlement_backups.create_backup_archive", return_value={"backup": "daily.tar.gz"}):
        first = run_due_daily_settlement_backup(now=now)
        second = run_due_daily_settlement_backup(now=now)

    run = SettlementRun.objects.get()
    assert first is not None
    assert second is not None
    assert SettlementRun.objects.count() == 1
    assert run.run_type == SettlementRun.RunType.DAILY_BACKUP
    assert first.status == DailySettlementBackupLog.Status.SUCCESS
    assert first.backup_file == "daily.tar.gz"
    assert second.pk == first.pk


@pytest.mark.django_db
def test_daily_backup_retries_failed_archive_with_existing_run(settings, tmp_path):
    settings.BACKUP_DIR = tmp_path
    DailySettlementBackupSettings.objects.create(enabled=True, run_time=time(5, 0))
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    ChargeFactory(participant=participant, unit_price=Decimal("12.00"))
    now = timezone.make_aware(datetime(2026, 7, 7, 5, 0))

    with patch(
        "billing.daily_settlement_backups.create_backup_archive",
        side_effect=[UpdateAgentError("Agent nicht erreichbar"), {"backup": "daily.tar.gz"}],
    ):
        first = run_due_daily_settlement_backup(now=now)
        second = run_due_daily_settlement_backup(now=now)

    assert first is not None
    assert second is not None
    assert first.pk == second.pk
    assert SettlementRun.objects.count() == 1
    assert second.status == DailySettlementBackupLog.Status.SUCCESS
    assert second.backup_file == "daily.tar.gz"


@pytest.mark.django_db
def test_daily_backup_logs_missing_active_camp():
    Camp.objects.all().delete()
    DailySettlementBackupSettings.objects.create(enabled=True, run_time=time(5, 0))
    now = timezone.make_aware(datetime(2026, 7, 7, 5, 0))

    result = run_due_daily_settlement_backup(now=now)

    assert result is not None
    assert result.status == DailySettlementBackupLog.Status.FAILED
    assert result.camp is None
    assert "Kein aktives Lager" in result.error


@pytest.mark.django_db
def test_backup_staging_contains_exports_and_manifest(settings, tmp_path):
    settings.BACKUP_DIR = tmp_path
    user = SuperUserFactory()
    participant = ParticipantFactory(first_name="Ada", last_name="Lovelace")
    ChargeFactory(participant=participant, unit_price=Decimal("12.00"))
    run = create_settlement_run(participant.camp, user, run_type=SettlementRun.RunType.DAILY_BACKUP)

    staging_path = build_settlement_backup_staging(run)

    csv_path = staging_path / f"abrechnung-{run.camp.year}-v{run.version}.csv"
    workbook_path = staging_path / f"abrechnung-{run.camp.year}-v{run.version}.xlsx"
    pdf_files = list((staging_path / "pdf").glob("*.pdf"))
    manifest = json.loads((staging_path / "manifest.json").read_text(encoding="utf-8"))
    workbook = load_workbook(BytesIO(workbook_path.read_bytes()), data_only=True)
    assert "Ada Lovelace" in csv_path.read_text(encoding="utf-8")
    assert workbook["Abrechnung"]["A2"].value == "Ada Lovelace"
    assert pdf_files and pdf_files[0].read_bytes().startswith(b"%PDF-")
    assert manifest["settlement_run"]["run_type"] == SettlementRun.RunType.DAILY_BACKUP
    assert manifest["participant_count"] == 1
