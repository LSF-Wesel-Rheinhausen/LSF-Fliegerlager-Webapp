import base64

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.core.management.base import BaseCommand
from py_vapid import Vapid


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class Command(BaseCommand):
    """Generate a VAPID key pair suitable for environment configuration."""

    help = "Erzeugt ein neues VAPID-Schlüsselpaar für Web Push."

    def handle(self, *args, **options):
        vapid = Vapid()
        vapid.generate_keys()
        public_key = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        private_value = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
        self.stdout.write(f"WEB_PUSH_VAPID_PUBLIC_KEY={_base64url(public_key)}")
        self.stdout.write(f"WEB_PUSH_VAPID_PRIVATE_KEY={_base64url(private_value)}")
