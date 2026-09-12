import time

from django.core.management.base import BaseCommand

from billing.account_recovery import send_due_account_recovery_requests
from billing.recovery_tokens import cleanup_account_recovery_artifacts


class Command(BaseCommand):
    """Resolve public recovery requests outside the HTTP response path."""

    help = "Verarbeitet ausstehende Kontowiederherstellungsanfragen."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="Dauerhaft als Worker ausführen")
        parser.add_argument("--interval", type=int, default=10, help="Sekunden zwischen Worker-Durchläufen")

    def handle(self, *args, **options):
        interval = max(5, options["interval"])
        while True:
            queued = send_due_account_recovery_requests()
            cleaned = cleanup_account_recovery_artifacts()
            self.stdout.write(
                f"Recovery-Durchlauf abgeschlossen: {queued} Anfragen eingeplant, "
                f"{cleaned} abgelaufene Artefakte entfernt."
            )
            if not options["loop"]:
                return
            time.sleep(interval)
