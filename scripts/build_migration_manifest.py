"""Render the deterministic OCI migration manifest used by release images."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import os
import re
import sys
from pathlib import Path

MIGRATION_NAME = re.compile(r"^(?P<name>\d+_[a-z0-9_]+)\.py$")


def _migration_class(tree: ast.Module) -> ast.ClassDef | None:
    return next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Migration"),
        None,
    )


def _assignment(migration: ast.ClassDef | None, name: str) -> ast.expr | None:
    if migration is None:
        return None
    for node in migration.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
    return None


def _dependencies(value: ast.expr | None) -> list[str]:
    if not isinstance(value, (ast.List, ast.Tuple)):
        raise ValueError("Unsupported migration dependency declaration.")
    dependencies = []
    for item in value.elts:
        try:
            dependency = ast.literal_eval(item)
        except (ValueError, TypeError):
            raise ValueError("Unsupported migration dependency declaration.") from None
        if not (
            isinstance(dependency, tuple)
            and len(dependency) == 2
            and all(isinstance(part, str) and part for part in dependency)
        ):
            raise ValueError("Unsupported migration dependency declaration.")
        dependencies.append(f"{dependency[0]}.{dependency[1]}")
    return sorted(dependencies)


def _call_name(call: ast.Call) -> str:
    function = call.func
    if isinstance(function, ast.Attribute):
        return function.attr
    if isinstance(function, ast.Name):
        return function.id
    return ""


def _has_reverse(call: ast.Call, keyword: str) -> bool:
    if len(call.args) >= 2 and not isinstance(call.args[1], ast.Constant):
        return True
    if len(call.args) >= 2 and call.args[1].value is not None:
        return True
    return any(
        item.arg == keyword and not (isinstance(item.value, ast.Constant) and item.value.value is None)
        for item in call.keywords
    )


def _is_reversible(value: ast.expr | None) -> bool:
    if not isinstance(value, (ast.List, ast.Tuple)):
        return False
    for operation in value.elts:
        if not isinstance(operation, ast.Call):
            return False
        name = _call_name(operation)
        if name == "RunPython" and not _has_reverse(operation, "reverse_code"):
            return False
        if name == "RunSQL" and not _has_reverse(operation, "reverse_sql"):
            return False
    return True


def render_manifest(paths: list[Path], dependencies_by_identifier: dict[str, list[str]] | None = None) -> str:
    """Return stable JSON describing migration identity, ancestry, and file hashes.

    ``dependencies_by_identifier`` supplies dependencies resolved by Django's
    migration graph. When omitted, dependencies are read as literal AST data.
    Raises ``ValueError`` when a source filename or dependency declaration
    cannot be represented safely, or when the supplied dependency map does not
    exactly cover the migration files. A missing map identifier raises
    ``KeyError`` before rendering an incomplete manifest.
    """
    entries = []
    migrations = []
    identifiers: set[str] = set()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if path.name == "__init__.py":
            continue
        match = MIGRATION_NAME.fullmatch(path.name)
        if not match:
            raise ValueError(f"Unsupported migration filename: {path.name}")
        app = path.parent.parent.name if path.parent.name == "migrations" else "billing"
        identifier = f"{app}.{match.group('name')}"
        identifiers.add(identifier)
        source = path.read_bytes()
        entry = {
            "path": f"{app}/migrations/{path.name}",
            "sha256": hashlib.sha256(source).hexdigest(),
        }
        tree = ast.parse(source, filename=str(path))
        migration = _migration_class(tree)
        entries.append(entry)
        migrations.append(
            {
                "dependencies": (
                    sorted(dependencies_by_identifier[identifier])
                    if dependencies_by_identifier is not None
                    else _dependencies(_assignment(migration, "dependencies"))
                ),
                "identifier": identifier,
                "reversible": _is_reversible(_assignment(migration, "operations")),
                "sha256": entry["sha256"],
            }
        )
    if dependencies_by_identifier is not None and identifiers != dependencies_by_identifier.keys():
        raise ValueError("Django dependencies do not match migration files.")
    return (
        json.dumps(
            {
                "files": sorted(entries, key=lambda entry: entry["path"]),
                "migrations": sorted(migrations, key=lambda migration: migration["identifier"]),
                "version": 1,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def installed_manifest() -> str:
    """Render the installed migrations using Django's resolved graph dependencies."""
    installed_migration_paths()
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(None)
    paths: list[Path] = []
    dependencies_by_identifier: dict[str, list[str]] = {}
    for key, migration in loader.disk_migrations.items():
        app, name = key
        module = importlib.import_module(migration.__module__)
        path = Path(module.__file__)
        paths.append(path)
        node = loader.graph.node_map[key]
        dependencies_by_identifier[f"{app}.{name}"] = [f"{parent.key[0]}.{parent.key[1]}" for parent in node.parents]
    return render_manifest(paths, dependencies_by_identifier)


def installed_migration_paths() -> list[Path]:
    """Return migration modules for every installed Django app that ships them."""
    source_root = Path(__file__).resolve().parents[1] / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    from django.apps import apps

    django.setup()
    paths: list[Path] = []
    for app_config in apps.get_app_configs():
        module_name = f"{app_config.name}.migrations"
        try:
            migration_module = importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            if error.name == module_name:
                continue
            raise
        for directory in getattr(migration_module, "__path__", ()):
            paths.extend(Path(directory).glob("*.py"))
    return paths


def verify_manifest_label(expected: str, actual: str) -> None:
    """Reject a label that differs from the installed image's migration manifest.

    The default empty object denotes unknown compatibility for local builds.
    Any nonempty claim must match the actual manifest, otherwise ValueError is
    raised. Malformed JSON also raises ValueError.
    """
    claimed = json.loads(expected)
    if claimed == {}:
        return
    if claimed != json.loads(actual):
        raise ValueError("Migration label does not match the installed image dependencies.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--verify-label")
    args = parser.parse_args()
    actual = render_manifest(list(args.root.glob("*.py"))) if args.root is not None else installed_manifest()
    if args.verify_label is not None:
        verify_manifest_label(args.verify_label, actual)
    else:
        print(actual, end="")


if __name__ == "__main__":
    main()
