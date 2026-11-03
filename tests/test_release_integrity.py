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


def test_manifest_rejects_unrecognized_migration_filename_but_ignores_package_init(tmp_path: Path) -> None:
    migrations = tmp_path / "billing" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "__init__.py").write_text("raise RuntimeError('must not execute')\n")
    unrecognized = migrations / "initial.py"
    unrecognized.write_text("class Migration:\n    dependencies = []\n    operations = []\n")

    with pytest.raises(ValueError, match="Unsupported migration filename"):
        render_manifest([migrations / "__init__.py", unrecognized])


def test_manifest_rejects_extra_dependency_map_entries(tmp_path: Path) -> None:
    path = _migration(tmp_path, "billing")
    with pytest.raises(ValueError, match="match migration files"):
        render_manifest([path], {"billing.0001_initial": [], "billing.0002_missing": []})


@pytest.mark.parametrize(
    "dependency",
    ["migrations.swappable_dependency(settings.AUTH_USER_MODEL)", "unknown_dependency()"],
)
def test_manifest_rejects_unsupported_dependency_instead_of_dropping_it(tmp_path: Path, dependency: str) -> None:
    path = _migration(tmp_path, "billing")
    path.write_text(
        f"""class Migration:
    dependencies = [("auth", "0001_initial"), {dependency}]
    operations = []
"""
    )
    with pytest.raises(ValueError, match="Unsupported migration dependency"):
        render_manifest([path])


@pytest.mark.parametrize(
    "dependencies",
    ["None", '[ ("auth", 1)]', '[ ("auth", "0001_initial"), unknown()]'],
)
def test_manifest_rejects_malformed_or_partially_supported_dependency_lists(tmp_path: Path, dependencies: str) -> None:
    path = _migration(tmp_path, "billing")
    path.write_text(f"class Migration:\n    dependencies = {dependencies}\n    operations = []\n")
    with pytest.raises(ValueError, match="Unsupported migration dependency"):
        render_manifest([path])


def test_installed_manifest_uses_django_resolved_swappable_dependencies():
    from scripts.build_migration_manifest import installed_manifest, verify_manifest_label

    actual = installed_manifest()
    manifest = json.loads(actual)
    admin = next(item for item in manifest["migrations"] if item["identifier"] == "admin.0001_initial")
    assert "auth.0001_initial" in admin["dependencies"]
    assert "contenttypes.0001_initial" in admin["dependencies"]
    verify_manifest_label(actual, installed_manifest())


def test_docker_verifies_manifest_against_final_installed_environment() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    verification = 'DJANGO_DEBUG=1 python scripts/build_migration_manifest.py --verify-label "$MIGRATION_MANIFEST"'
    assert verification in dockerfile
    assert dockerfile.index("COPY --from=builder /opt/venv /opt/venv") < dockerfile.index(verification)
    assert dockerfile.index("COPY --chown=app:app src ./src") < dockerfile.index(verification)
    assert "COPY scripts/build_migration_manifest.py ./scripts/build_migration_manifest.py" in dockerfile
