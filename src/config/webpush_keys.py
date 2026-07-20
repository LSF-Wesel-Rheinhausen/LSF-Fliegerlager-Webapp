from __future__ import annotations

import base64
import logging
import os
import tempfile
from binascii import Error as Base64Error
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid

LOGGER = logging.getLogger(__name__)
PUBLIC_KEY_FILENAME = "public.key"
PRIVATE_KEY_FILENAME = "private.key"


class WebPushKeyError(RuntimeError):
    """Report incomplete or unreadable Web Push key configuration."""


@dataclass(frozen=True)
class WebPushKeys:
    """Contain a base64url-encoded VAPID public/private key pair."""

    public_key: str
    private_key: str


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _validate_keys(keys: WebPushKeys) -> WebPushKeys:
    try:
        public_bytes = _decode_base64url(keys.public_key)
        private_bytes = _decode_base64url(keys.private_key)
        if len(private_bytes) != 32:
            raise ValueError("VAPID private key must contain 32 bytes.")
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_bytes)
        private_key = ec.derive_private_key(int.from_bytes(private_bytes, "big"), ec.SECP256R1())
    except (Base64Error, UnicodeEncodeError, ValueError) as error:
        raise WebPushKeyError("Web Push keys must form a valid matching VAPID key pair.") from error
    if public_key.public_numbers() != private_key.public_key().public_numbers():
        raise WebPushKeyError("Web Push keys must form a valid matching VAPID key pair.")
    return keys


def generate_webpush_keys() -> WebPushKeys:
    """Generate a VAPID key pair in the format expected by pywebpush."""

    vapid = Vapid()
    vapid.generate_keys()
    public_key = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    private_key = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    return WebPushKeys(public_key=_base64url(public_key), private_key=_base64url(private_key))


def _environment_keys(environment: Mapping[str, str]) -> WebPushKeys | None:
    public_key = environment.get("WEB_PUSH_VAPID_PUBLIC_KEY", "").strip()
    private_key = environment.get("WEB_PUSH_VAPID_PRIVATE_KEY", "").strip()
    if bool(public_key) != bool(private_key):
        raise WebPushKeyError("WEB_PUSH_VAPID_PUBLIC_KEY and WEB_PUSH_VAPID_PRIVATE_KEY must be configured together.")
    if public_key:
        return _validate_keys(WebPushKeys(public_key=public_key, private_key=private_key))
    return None


def _file_keys(key_directory: Path) -> WebPushKeys | None:
    public_path = key_directory / PUBLIC_KEY_FILENAME
    private_path = key_directory / PRIVATE_KEY_FILENAME
    if public_path.exists() != private_path.exists():
        raise WebPushKeyError("Web Push key files must both exist or both be absent.")
    if not public_path.exists():
        return None
    try:
        public_key = public_path.read_text(encoding="ascii").strip()
        private_key = private_path.read_text(encoding="ascii").strip()
    except OSError as error:
        raise WebPushKeyError(f"Cannot read Web Push key files in {key_directory}.") from error
    if not public_key or not private_key:
        raise WebPushKeyError(f"Web Push key files in {key_directory} must not be empty.")
    return _validate_keys(WebPushKeys(public_key=public_key, private_key=private_key))


def load_webpush_keys(environment: Mapping[str, str], key_directory: Path) -> WebPushKeys | None:
    """Load a complete VAPID pair, preferring explicit environment variables."""

    return _environment_keys(environment) or _file_keys(key_directory)


def _atomic_write_secret(path: Path, value: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as secret_file:
            secret_file.write(value + "\n")
            secret_file.flush()
            os.fsync(secret_file.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def ensure_webpush_key_files(
    environment: Mapping[str, str],
    key_directory: Path,
) -> WebPushKeys | None:
    """Create one persistent VAPID pair when Push is enabled and no keys exist."""

    if environment.get("WEB_PUSH_ENABLED", "0") != "1":
        return None
    configured = load_webpush_keys(environment, key_directory)
    if configured is not None:
        return configured

    key_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_directory.chmod(0o700)
    generated = generate_webpush_keys()
    _atomic_write_secret(key_directory / PUBLIC_KEY_FILENAME, generated.public_key)
    _atomic_write_secret(key_directory / PRIVATE_KEY_FILENAME, generated.private_key)
    return generated


def main() -> int:
    """Ensure container Web Push keys exist before Django loads settings."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    key_directory = Path(os.getenv("WEB_PUSH_KEY_DIR", "/run/secrets/webpush"))
    try:
        keys = ensure_webpush_key_files(os.environ, key_directory)
    except WebPushKeyError:
        LOGGER.exception("Web Push key initialization aborted")
        return 1
    if keys is not None:
        LOGGER.info("Web Push key configuration is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
