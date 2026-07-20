import json
from pathlib import Path

import pytest

from config.persistence_migration import (
    LegacyPersistence,
    PersistenceMigrationError,
    migrate_persistence,
)


def _legacy_paths(tmp_path: Path) -> LegacyPersistence:
    legacy_root = tmp_path / "legacy"
    return LegacyPersistence(
        postgres=legacy_root / "postgres",
        media=legacy_root / "media",
        backups=legacy_root / "backups",
        updater_state=legacy_root / "updater-state",
    )


def test_migration_copies_legacy_data_and_writes_versioned_marker(tmp_path: Path):
    legacy = _legacy_paths(tmp_path)
    (legacy.postgres / "base").mkdir(parents=True)
    (legacy.postgres / "PG_VERSION").write_text("16\n", encoding="ascii")
    (legacy.postgres / "base" / "database-file").write_bytes(b"postgres-data")
    legacy.media.mkdir(parents=True)
    (legacy.media / "receipt.pdf").write_bytes(b"receipt")
    legacy.backups.mkdir(parents=True)
    (legacy.backups / "settlement.zip").write_bytes(b"archive")
    legacy.updater_state.mkdir(parents=True)
    (legacy.updater_state / "status.json").write_text('{"state":"idle"}', encoding="utf-8")

    result = migrate_persistence(tmp_path / "persistent", legacy)

    assert result.migrated is True
    assert result.copied_sources == ("postgres", "media", "backups", "updater-state")
    assert (tmp_path / "persistent/postgres/base/database-file").read_bytes() == b"postgres-data"
    assert (tmp_path / "persistent/media/receipt.pdf").read_bytes() == b"receipt"
    assert (tmp_path / "persistent/backups/settlement.zip").read_bytes() == b"archive"
    assert json.loads((tmp_path / "persistent/migration/v1.json").read_text(encoding="utf-8")) == {
        "copied_sources": ["postgres", "media", "backups", "updater-state"],
        "version": 1,
    }


def test_migration_creates_empty_layout_for_new_installation(tmp_path: Path):
    persistent_root = tmp_path / "persistent"
    for relative_path in ("postgres", "media", "backups", "updater-state", "secrets/webpush"):
        (persistent_root / relative_path).mkdir(parents=True)

    result = migrate_persistence(persistent_root, _legacy_paths(tmp_path))

    assert result.migrated is True
    assert result.copied_sources == ()
    for relative_path in ("postgres", "media", "backups", "updater-state", "secrets/webpush"):
        assert (tmp_path / "persistent" / relative_path).is_dir()


def test_completed_migration_is_idempotent(tmp_path: Path):
    legacy = _legacy_paths(tmp_path)
    legacy.media.mkdir(parents=True)
    (legacy.media / "existing.txt").write_text("original", encoding="utf-8")
    persistent_root = tmp_path / "persistent"

    migrate_persistence(persistent_root, legacy)
    (legacy.media / "existing.txt").write_text("changed", encoding="utf-8")
    result = migrate_persistence(persistent_root, legacy)

    assert result.migrated is False
    assert (persistent_root / "media/existing.txt").read_text(encoding="utf-8") == "original"


def test_migration_refuses_running_legacy_postgres(tmp_path: Path):
    legacy = _legacy_paths(tmp_path)
    legacy.postgres.mkdir(parents=True)
    (legacy.postgres / "PG_VERSION").write_text("16\n", encoding="ascii")
    (legacy.postgres / "postmaster.pid").write_text("123", encoding="ascii")

    with pytest.raises(PersistenceMigrationError, match="postmaster.pid"):
        migrate_persistence(tmp_path / "persistent", legacy)


def test_migration_refuses_incompatible_postgres_version(tmp_path: Path):
    legacy = _legacy_paths(tmp_path)
    legacy.postgres.mkdir(parents=True)
    (legacy.postgres / "PG_VERSION").write_text("15\n", encoding="ascii")

    with pytest.raises(PersistenceMigrationError, match="PostgreSQL 15"):
        migrate_persistence(tmp_path / "persistent", legacy)


def test_migration_refuses_populated_target_without_marker(tmp_path: Path):
    persistent_root = tmp_path / "persistent"
    (persistent_root / "media").mkdir(parents=True)
    (persistent_root / "media" / "unknown.txt").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(PersistenceMigrationError, match="already contains data"):
        migrate_persistence(persistent_root, _legacy_paths(tmp_path))


def test_migration_refuses_backup_source_that_is_also_the_target(tmp_path: Path):
    persistent_root = tmp_path / "persistent"
    persistent_root.mkdir()
    legacy = _legacy_paths(tmp_path)
    aliased_legacy = LegacyPersistence(
        postgres=legacy.postgres,
        media=legacy.media,
        backups=persistent_root,
        updater_state=legacy.updater_state,
    )

    with pytest.raises(PersistenceMigrationError, match="must not reference the persistence target"):
        migrate_persistence(persistent_root, aliased_legacy)
