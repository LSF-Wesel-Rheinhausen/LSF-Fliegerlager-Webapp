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
        return []
    dependencies = []
    for item in value.elts:
        try:
            dependency = ast.literal_eval(item)
        except (ValueError, TypeError):
            continue
        if isinstance(dependency, tuple) and len(dependency) == 2 and all(isinstance(part, str) for part in dependency):
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


def render_manifest(paths: list[Path]) -> str:
    """Return stable JSON describing migration identity, ancestry, and file hashes."""
    entries = []
    migrations = []
    for path in sorted(paths, key=lambda item: item.as_posix()):
        match = MIGRATION_NAME.fullmatch(path.name)
        if not match:
            continue
        app = path.parent.parent.name if path.parent.name == "migrations" else "billing"
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
                "dependencies": _dependencies(_assignment(migration, "dependencies")),
                "identifier": f"{app}.{match.group('name')}",
                "reversible": _is_reversible(_assignment(migration, "operations")),
                "sha256": entry["sha256"],
            }
        )
    return (
        json.dumps(
            {
                "files": entries,
                "migrations": migrations,
                "version": 1,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    paths = list(args.root.glob("*.py")) if args.root is not None else installed_migration_paths()
    print(render_manifest(paths), end="")


if __name__ == "__main__":
    main()
