import base64
from pathlib import Path

import pytest

from config.webpush_keys import (
    WebPushKeyError,
    ensure_webpush_key_files,
    generate_webpush_keys,
    load_webpush_keys,
)


def _decode_base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def test_disabled_web_push_does_not_create_keys(tmp_path: Path):
    result = ensure_webpush_key_files({"WEB_PUSH_ENABLED": "0"}, tmp_path)

    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_enabled_web_push_generates_persistent_key_pair(tmp_path: Path):
    environment = {"WEB_PUSH_ENABLED": "1"}

    generated = ensure_webpush_key_files(environment, tmp_path)
    loaded = load_webpush_keys(environment, tmp_path)

    assert generated == loaded
    assert generated is not None
    assert len(_decode_base64url(generated.public_key)) == 65
    assert len(_decode_base64url(generated.private_key)) == 32
    assert (tmp_path / "public.key").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "private.key").stat().st_mode & 0o777 == 0o600


def test_existing_key_pair_is_reused_without_rotation(tmp_path: Path):
    environment = {"WEB_PUSH_ENABLED": "1"}
    first = ensure_webpush_key_files(environment, tmp_path)

    second = ensure_webpush_key_files(environment, tmp_path)

    assert second == first


def test_environment_key_pair_takes_precedence_over_files(tmp_path: Path):
    keys = generate_webpush_keys()
    environment = {
        "WEB_PUSH_ENABLED": "1",
        "WEB_PUSH_VAPID_PUBLIC_KEY": keys.public_key,
        "WEB_PUSH_VAPID_PRIVATE_KEY": keys.private_key,
    }

    result = ensure_webpush_key_files(environment, tmp_path)

    assert result is not None
    assert result == keys
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("filename", ["public.key", "private.key"])
def test_partial_file_key_pair_is_rejected(tmp_path: Path, filename: str):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / filename).write_text("partial", encoding="ascii")

    with pytest.raises(WebPushKeyError, match="both exist or both be absent"):
        ensure_webpush_key_files({"WEB_PUSH_ENABLED": "1"}, tmp_path)


def test_partial_environment_key_pair_is_rejected(tmp_path: Path):
    with pytest.raises(WebPushKeyError, match="must be configured together"):
        ensure_webpush_key_files(
            {"WEB_PUSH_ENABLED": "1", "WEB_PUSH_VAPID_PUBLIC_KEY": "only-public"},
            tmp_path,
        )


def test_invalid_file_key_pair_is_rejected(tmp_path: Path):
    (tmp_path / "public.key").write_text("not-a-public-key", encoding="ascii")
    (tmp_path / "private.key").write_text("not-a-private-key", encoding="ascii")

    with pytest.raises(WebPushKeyError, match="valid matching VAPID key pair"):
        load_webpush_keys({"WEB_PUSH_ENABLED": "1"}, tmp_path)
