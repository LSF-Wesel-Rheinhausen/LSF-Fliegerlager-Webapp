import time

from django.core.management.base import BaseCommand

from billing.account_recovery import send_due_account_recovery_requests


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
            self.stdout.write(f"Recovery-Durchlauf abgeschlossen: {queued} Anfragen eingeplant.")
            if not options["loop"]:
                return
            time.sleep(interval)
