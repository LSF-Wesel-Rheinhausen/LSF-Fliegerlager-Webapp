import time

from django.conf import settings
from django.core.management.base import BaseCommand

from billing.notifications import cleanup_push_messages, generate_scheduled_notifications, send_due_push_messages


class Command(BaseCommand):
    """Generate scheduled push messages and deliver the database outbox."""

    help = "Verarbeitet terminierte und ausstehende Push-Benachrichtigungen."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="Dauerhaft als Worker ausführen")
        parser.add_argument(
            "--interval",
            type=int,
            default=settings.WEB_PUSH_WORKER_INTERVAL_SECONDS,
            help="Sekunden zwischen Worker-Durchläufen",
        )

    def handle(self, *args, **options):
        if not settings.WEB_PUSH_ENABLED:
            self.stdout.write("Push-Benachrichtigungen sind deaktiviert.")
            if options["loop"]:
                while True:
                    time.sleep(max(5, options["interval"]))
            return
        interval = max(5, options["interval"])
        while True:
            scheduled = generate_scheduled_notifications()
            result = send_due_push_messages()
            cleanup_push_messages()
            self.stdout.write(
                "Push-Durchlauf abgeschlossen: "
                f"{scheduled} geplant, {result.sent} gesendet, {result.retried} erneut eingeplant, "
                f"{result.failed} fehlgeschlagen, {result.removed_subscriptions} Geräte entfernt."
            )
            if not options["loop"]:
                return
            time.sleep(interval)
