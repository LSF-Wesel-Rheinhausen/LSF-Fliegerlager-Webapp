import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings


class EmailCredentialError(ValueError):
    """Report that a stored SMTP credential cannot be decrypted."""


def _credential_cipher() -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"fliegerlager-email-configuration-v1",
        info=b"smtp-password",
    ).derive(settings.SECRET_KEY.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_email_password(password: str) -> str:
    """Encrypt an SMTP password using the application's existing secret key."""
    if not password:
        return ""
    return _credential_cipher().encrypt(password.encode("utf-8")).decode("ascii")


def decrypt_email_password(token: str) -> str:
    """Decrypt a stored SMTP password.

    Raises:
        EmailCredentialError: If the token is invalid or the application secret changed.
    """
    if not token:
        return ""
    try:
        return _credential_cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as error:
        raise EmailCredentialError("Das gespeicherte SMTP-Passwort kann nicht entschlüsselt werden.") from error
