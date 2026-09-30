"""Verify that published migration labels describe the installed image."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.build_migration_manifest import render_manifest

ROOT = Path(__file__).parents[1]


def _migration(root: Path, app: str, content: str = "") -> Path:
    path = root / app / "migrations" / "0001_initial.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("class Migration:\n    dependencies = []\n    operations = []\n" + content)
    return path


@pytest.mark.parametrize("claim", ["broken", "[]", '{"version":1}'])
def test_image_manifest_verification_rejects_invalid_claims(tmp_path: Path, claim: str) -> None:
    migration = _migration(tmp_path, "billing")
    result = _verify(migration.parent, claim)
    assert result.returncode != 0
    assert "unrecognized arguments" not in result.stderr


def _verify(root: Path, claim: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_migration_manifest.py"),
            "--root",
            str(root),
            "--verify-label",
            claim,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_image_manifest_verification_accepts_exact_label_and_unknown_default(tmp_path: Path) -> None:
    migration = _migration(tmp_path, "billing")
    for claim in (render_manifest([migration]), "{}"):
        result = _verify(migration.parent, claim)
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""


def test_image_manifest_verification_rejects_different_dependency_files(tmp_path: Path) -> None:
    migration = _migration(tmp_path, "auth")
    claim = render_manifest([migration])
    migration.write_text(migration.read_text() + "# changed dependency release\n")
    result = _verify(migration.parent, claim)
    assert result.returncode != 0
    assert "does not match" in result.stderr


def test_manifest_order_is_independent_of_dependency_installation_prefix(tmp_path: Path) -> None:
    host = [_migration(tmp_path / "host/a", "billing"), _migration(tmp_path / "host/z", "auth")]
    image = [_migration(tmp_path / "image/z", "billing"), _migration(tmp_path / "image/a", "auth")]
    assert render_manifest(host) == render_manifest(image)
    assert [item["identifier"] for item in json.loads(render_manifest(host))["migrations"]] == [
        "auth.0001_initial",
        "billing.0001_initial",
    ]


def test_docker_verifies_manifest_against_final_installed_environment() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    verification = 'DJANGO_DEBUG=1 python scripts/build_migration_manifest.py --verify-label "$MIGRATION_MANIFEST"'
    assert verification in dockerfile
    assert dockerfile.index("COPY --from=builder /opt/venv /opt/venv") < dockerfile.index(verification)
    assert dockerfile.index("COPY --chown=app:app src ./src") < dockerfile.index(verification)
    assert "COPY scripts/build_migration_manifest.py ./scripts/build_migration_manifest.py" in dockerfile
