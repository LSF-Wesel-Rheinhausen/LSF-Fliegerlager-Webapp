import time
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from billing.daily_settlement_backups import run_due_daily_settlement_backup


class Command(BaseCommand):
    """Run or schedule the daily settlement backup check."""

    help = "Creates the configured daily settlement run and backup archive when due."

    def add_arguments(self, parser: Any) -> None:
        """Register command line options."""
        parser.add_argument("--loop", action="store_true", help="Keep checking on a fixed interval.")
        parser.add_argument(
            "--interval",
            type=int,
            default=settings.DAILY_SETTLEMENT_BACKUP_INTERVAL_SECONDS,
            help="Seconds between checks when --loop is used.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Execute the backup check once or continuously."""
        while True:
            log = run_due_daily_settlement_backup()
            if log is None:
                self.stdout.write("Kein tägliches Abrechnungs-Backup fällig.")
            else:
                self.stdout.write(f"Tägliches Abrechnungs-Backup: {log.get_status_display()} ({log.run_date}).")
            if not options["loop"]:
                return
            time.sleep(options["interval"])
