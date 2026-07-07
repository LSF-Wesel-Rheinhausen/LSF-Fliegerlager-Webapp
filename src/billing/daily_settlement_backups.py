from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .deployment_updates import UpdateAgentError, create_backup_archive
from .exporters import settlement_run_csv_bytes, settlement_run_workbook_bytes, settlement_snapshot_pdf_bytes
from .models import Camp, DailySettlementBackupLog, DailySettlementBackupSettings, SettlementRun
from .services import create_settlement_run

logger = logging.getLogger(__name__)


def update_daily_backup_settings(*, enabled: bool, run_time: Any) -> DailySettlementBackupSettings:
    """Persist the singleton configuration for automated daily settlement backups."""
    backup_settings = DailySettlementBackupSettings.load()
    backup_settings.enabled = enabled
    backup_settings.run_time = run_time
    backup_settings.save(update_fields=["enabled", "run_time", "updated_at"])
    return backup_settings


def build_settlement_backup_staging(run: SettlementRun) -> Path:
    """Create export files for a settlement run under the shared backup volume."""
    backup_root = Path(settings.BACKUP_DIR).resolve()
    staging_root = backup_root / "staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    staging_path = Path(
        tempfile.mkdtemp(prefix=f"settlement-v{run.version}-", dir=staging_root),
    )
    pdf_dir = staging_path / "pdf"
    pdf_dir.mkdir()

    csv_name = f"abrechnung-{run.camp.year}-v{run.version}.csv"
    workbook_name = f"abrechnung-{run.camp.year}-v{run.version}.xlsx"
    (staging_path / csv_name).write_bytes(settlement_run_csv_bytes(run))
    (staging_path / workbook_name).write_bytes(settlement_run_workbook_bytes(run))

    pdf_files: list[str] = []
    for snapshot in run.settlements.select_related("run", "run__camp").order_by("participant_name", "pk"):
        pdf_name = f"abrechnung-{snapshot.pk}-v{run.version}.pdf"
        (pdf_dir / pdf_name).write_bytes(settlement_snapshot_pdf_bytes(snapshot))
        pdf_files.append(f"pdf/{pdf_name}")

    manifest = {
        "kind": "daily_settlement_backup",
        "created_at": timezone.now().isoformat(),
        "camp": {"id": run.camp_id, "name": run.camp.name, "year": run.camp.year},
        "settlement_run": {"id": run.pk, "version": run.version, "run_type": run.run_type},
        "participant_count": run.participant_count,
        "files": [csv_name, workbook_name, *pdf_files],
    }
    (staging_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return staging_path


def _relative_to_backup_root(path: Path) -> str:
    backup_root = Path(settings.BACKUP_DIR).resolve()
    return path.resolve().relative_to(backup_root).as_posix()


def _claim_daily_backup_log(camp: Camp | None, run_date: Any) -> tuple[DailySettlementBackupLog, bool] | None:
    try:
        with transaction.atomic():
            existing_log = (
                DailySettlementBackupLog.objects.select_for_update().filter(camp=camp, run_date=run_date).first()
            )
            if existing_log is None:
                return DailySettlementBackupLog.objects.create(camp=camp, run_date=run_date), True
            if existing_log.status != DailySettlementBackupLog.Status.FAILED:
                return existing_log, False
            existing_log.status = DailySettlementBackupLog.Status.RUNNING
            existing_log.error = ""
            existing_log.backup_file = ""
            existing_log.started_at = timezone.now()
            existing_log.finished_at = None
            existing_log.save(
                update_fields=["status", "error", "backup_file", "started_at", "finished_at", "updated_at"]
            )
            return existing_log, True
    except IntegrityError:
        return None


def run_due_daily_settlement_backup(*, now: Any | None = None) -> DailySettlementBackupLog | None:
    """Run the configured daily settlement backup when the scheduled time is due."""
    backup_settings = DailySettlementBackupSettings.load()
    if not backup_settings.enabled:
        return None

    current = timezone.localtime(now or timezone.now())
    if current.time() < backup_settings.run_time:
        return None

    camp = Camp.objects.filter(is_active=True).first()
    run_date = current.date()
    claimed_log = _claim_daily_backup_log(camp, run_date)
    if claimed_log is None:
        return DailySettlementBackupLog.objects.filter(camp=camp, run_date=run_date).first()
    log, should_run = claimed_log
    if not should_run:
        return log

    if camp is None:
        log.status = DailySettlementBackupLog.Status.FAILED
        log.error = "Kein aktives Lager gefunden."
        log.finished_at = timezone.now()
        log.save(update_fields=["status", "error", "finished_at", "updated_at"])
        return log

    staging_path: Path | None = None
    try:
        run = log.settlement_run or create_settlement_run(camp, None, run_type=SettlementRun.RunType.DAILY_BACKUP)
        if log.settlement_run_id is None:
            log.settlement_run = run
            log.save(update_fields=["settlement_run", "updated_at"])
        staging_path = build_settlement_backup_staging(run)
        archive_prefix = f"daily-settlement-{camp.year}-v{run.version}-{run_date:%Y%m%d}"
        response = create_backup_archive(_relative_to_backup_root(staging_path), archive_prefix)
        log.status = DailySettlementBackupLog.Status.SUCCESS
        log.settlement_run = run
        log.backup_file = str(response.get("backup", ""))
        log.finished_at = timezone.now()
        log.save(update_fields=["status", "settlement_run", "backup_file", "finished_at", "updated_at"])
    except (OSError, ValueError, UpdateAgentError) as error:
        logger.exception(
            "Tägliches Abrechnungs-Backup fehlgeschlagen",
            extra={"camp_id": camp.pk, "run_date": run_date},
        )
        log.status = DailySettlementBackupLog.Status.FAILED
        log.error = str(error)
        log.finished_at = timezone.now()
        log.save(update_fields=["status", "error", "finished_at", "updated_at"])
    finally:
        if staging_path is not None:
            shutil.rmtree(staging_path, ignore_errors=True)
    return log
