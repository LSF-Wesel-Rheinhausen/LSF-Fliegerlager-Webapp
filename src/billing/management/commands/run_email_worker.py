import smtplib
import time
from typing import Any

from django.core.management.base import BaseCommand

from billing.email_credentials import EmailCredentialError
from billing.email_delivery import send_due_email_deliveries


class Command(BaseCommand):
    """Deliver only email outbox entries created by explicit administrator actions."""

    help = "Verarbeitet manuell bestätigte Informations- und Rechnungs-E-Mails."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--loop", action="store_true", help="Dauerhaft als Worker ausführen")
        parser.add_argument("--interval", type=int, default=10, help="Sekunden zwischen Worker-Durchläufen")

    def handle(self, *args: Any, **options: Any) -> None:
        interval = max(5, options["interval"])
        while True:
            try:
                result = send_due_email_deliveries()
            except (EmailCredentialError, smtplib.SMTPException, OSError):
                self.stderr.write(
                    self.style.ERROR("E-Mail-Durchlauf fehlgeschlagen: SMTP-Zugangsdaten oder Verbindung prüfen.")
                )
            else:
                self.stdout.write(
                    "E-Mail-Durchlauf abgeschlossen: "
                    f"{result.sent} gesendet, {result.retried} erneut eingeplant, "
                    f"{result.failed} fehlgeschlagen."
                )
            if not options["loop"]:
                return
            time.sleep(interval)
