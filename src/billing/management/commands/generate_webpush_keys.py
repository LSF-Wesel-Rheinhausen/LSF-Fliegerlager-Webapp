from django.core.management.base import BaseCommand

from config.webpush_keys import generate_webpush_keys


class Command(BaseCommand):
    """Generate a VAPID key pair suitable for environment configuration."""

    help = "Erzeugt ein neues VAPID-Schlüsselpaar für Web Push."

    def handle(self, *args, **options):
        keys = generate_webpush_keys()
        self.stdout.write(f"WEB_PUSH_VAPID_PUBLIC_KEY={keys.public_key}")
        self.stdout.write(f"WEB_PUSH_VAPID_PRIVATE_KEY={keys.private_key}")
