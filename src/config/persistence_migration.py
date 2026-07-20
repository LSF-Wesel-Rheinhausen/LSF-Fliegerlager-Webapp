from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)
MIGRATION_VERSION = 1
TARGET_DIRECTORIES = ("postgres", "media", "backups", "updater-state")


class PersistenceMigrationError(RuntimeError):
    """Report an unsafe or inconsistent persistence migration state."""


@dataclass(frozen=True)
class LegacyPersistence:
    """Describe the read-only legacy storage locations."""

    postgres: Path
    media: Path
    backups: Path
    updater_state: Path


@dataclass(frozen=True)
class MigrationResult:
    """Describe whether a migration ran and which legacy sources were copied."""

    migrated: bool
    copied_sources: tuple[str, ...]


def _directory_has_content(path: Path) -> bool:
    return path.is_dir() and next(path.iterdir(), None) is not None


def _tree_contains_data(path: Path) -> bool:
    if not path.is_dir():
        return path.exists() or path.is_symlink()
    return any(child.is_symlink() or not child.is_dir() for child in path.rglob("*"))


def _validate_completed_migration(root: Path, marker_path: Path) -> MigrationResult:
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PersistenceMigrationError(f"Cannot read migration marker {marker_path}.") from error

    if marker.get("version") != MIGRATION_VERSION:
        raise PersistenceMigrationError(f"Unsupported persistence migration marker in {marker_path}.")

    required = (*TARGET_DIRECTORIES, "secrets/webpush")
    missing = [name for name in required if not (root / name).is_dir()]
    if missing:
        raise PersistenceMigrationError(
            f"Completed persistence migration is missing directories: {', '.join(missing)}."
        )

    copied_sources = marker.get("copied_sources", [])
    if not isinstance(copied_sources, list) or not all(isinstance(name, str) for name in copied_sources):
        raise PersistenceMigrationError(f"Invalid persistence migration marker in {marker_path}.")
    return MigrationResult(migrated=False, copied_sources=tuple(copied_sources))


def _validate_empty_target(root: Path, marker_directory: Path) -> None:
    known_paths = {root / name for name in TARGET_DIRECTORIES}
    known_paths.update({root / "secrets", marker_directory})
    unexpected = [path for path in root.iterdir() if path not in known_paths]
    populated = [path for path in known_paths if _tree_contains_data(path)]
    if unexpected or populated:
        raise PersistenceMigrationError(
            f"Persistence target {root} already contains data but has no completed migration marker."
        )


def _validate_legacy_postgres(postgres_path: Path, expected_major: str) -> None:
    if not _directory_has_content(postgres_path):
        return
    if (postgres_path / "postmaster.pid").exists():
        raise PersistenceMigrationError(
            "Legacy PostgreSQL contains postmaster.pid. Stop the old stack before migrating."
        )

    version_path = postgres_path / "PG_VERSION"
    if not version_path.is_file():
        raise PersistenceMigrationError("Legacy PostgreSQL data has no PG_VERSION file.")
    version = version_path.read_text(encoding="ascii").strip()
    if version != expected_major:
        raise PersistenceMigrationError(
            f"Legacy PostgreSQL {version} is incompatible with the expected PostgreSQL {expected_major}."
        )


def _validate_distinct_sources(root: Path, sources: tuple[tuple[str, Path], ...]) -> None:
    for name, source in sources:
        if not source.exists():
            continue
        destination = root / name
        aliases_root = os.path.samefile(source, root)
        aliases_destination = destination.exists() and os.path.samefile(source, destination)
        if aliases_root or aliases_destination:
            raise PersistenceMigrationError(f"Legacy {name} source must not reference the persistence target.")


def _copy_source(source: Path, destination: Path) -> bool:
    destination.mkdir(parents=True, exist_ok=True)
    if not _directory_has_content(source):
        return False
    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True, copy_function=shutil.copy2)
    return True


def _write_marker(marker_path: Path, copied_sources: tuple[str, ...]) -> None:
    payload = {"copied_sources": list(copied_sources), "version": MIGRATION_VERSION}
    temporary_path = marker_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_path, marker_path)


def migrate_persistence(
    root: Path,
    legacy: LegacyPersistence,
    *,
    expected_postgres_major: str = "16",
) -> MigrationResult:
    """Migrate legacy volumes into one versioned persistence directory.

    Existing legacy sources remain untouched. A populated target without a valid
    completion marker is rejected to avoid merging or overwriting unknown data.
    """

    root.mkdir(parents=True, exist_ok=True)
    marker_directory = root / "migration"
    marker_path = marker_directory / f"v{MIGRATION_VERSION}.json"
    if marker_path.is_file():
        return _validate_completed_migration(root, marker_path)

    sources = (
        ("postgres", legacy.postgres),
        ("media", legacy.media),
        ("backups", legacy.backups),
        ("updater-state", legacy.updater_state),
    )
    _validate_distinct_sources(root, sources)
    marker_directory.mkdir(exist_ok=True)
    _validate_empty_target(root, marker_directory)
    _validate_legacy_postgres(legacy.postgres, expected_postgres_major)

    copied_sources = tuple(name for name, source in sources if _copy_source(source, root / name))
    (root / "secrets/webpush").mkdir(parents=True, exist_ok=True)
    _write_marker(marker_path, copied_sources)
    return MigrationResult(migrated=True, copied_sources=copied_sources)


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    for current_root, directories, files in os.walk(path, followlinks=False):
        os.chown(current_root, uid, gid, follow_symlinks=False)
        for name in (*directories, *files):
            target = Path(current_root) / name
            if not target.is_symlink():
                os.chown(target, uid, gid, follow_symlinks=False)


def prepare_runtime_permissions(root: Path, *, app_uid: int = 10001, app_gid: int = 10001) -> None:
    """Grant the unprivileged application access to its writable directories."""

    for name in ("media", "backups", "secrets"):
        _chown_tree(root / name, app_uid, app_gid)
    (root / "secrets").chmod(0o700)
    (root / "secrets/webpush").chmod(0o700)


def main() -> int:
    """Run the container migration against its fixed mount points."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    root = Path(os.getenv("PERSISTENCE_ROOT", "/data"))
    legacy = LegacyPersistence(
        postgres=Path("/legacy/postgres"),
        media=Path("/legacy/media"),
        backups=Path("/legacy/backups"),
        updater_state=Path("/legacy/updater-state"),
    )
    try:
        result = migrate_persistence(
            root,
            legacy,
            expected_postgres_major=os.getenv("POSTGRES_MAJOR", "16"),
        )
        prepare_runtime_permissions(root)
    except PersistenceMigrationError:
        LOGGER.exception("Persistence migration aborted")
        return 1

    action = "completed" if result.migrated else "already complete"
    LOGGER.info("Persistence migration %s; copied sources: %s", action, result.copied_sources)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
