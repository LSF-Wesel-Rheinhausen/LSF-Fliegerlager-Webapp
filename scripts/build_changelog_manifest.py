#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_DIR = ROOT / "changelog"


def git_output(*args: str) -> str:
    """Run git and return stripped stdout."""
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def last_revision_for(path: Path) -> str:
    """Return the mainline commit that introduced or last changed a changelog file."""
    output = git_output("log", "--first-parent", "-1", "--format=%H", "--", str(path.relative_to(ROOT)))
    return output or "unknown"


def revision_versions() -> dict[str, int]:
    """Return deterministic first-parent build versions from oldest to newest."""
    revisions = git_output("rev-list", "--reverse", "--first-parent", "HEAD").splitlines()
    return {revision: version for version, revision in enumerate(revisions, start=1)}


def changelog_title_and_body(path: Path) -> tuple[str, str]:
    """Extract a concise title and body from a Markdown changelog entry."""
    lines = path.read_text(encoding="utf-8").splitlines()
    title = path.stem.replace("-", " ")
    body_lines: list[str] = []
    title_found = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if title_found:
                body_lines.append("")
            continue
        if not title_found:
            title = stripped.lstrip("#").lstrip("-*").strip() or title
            title_found = True
            continue
        body_lines.append(line.rstrip())

    return title, "\n".join(body_lines).strip()


def build_manifest() -> list[dict[str, str]]:
    """Build the changelog manifest consumed by the deployment updater."""
    versions = revision_versions()
    entries = []
    for path in sorted(CHANGELOG_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        revision = last_revision_for(path)
        title, body = changelog_title_and_body(path)
        entries.append(
            {
                "version": str(versions.get(revision, 0)),
                "revision": revision,
                "path": str(path.relative_to(ROOT)),
                "title": title,
                "body": body,
            }
        )
    return sorted(entries, key=lambda entry: (int(entry["version"]), entry["path"]))


if __name__ == "__main__":
    print(json.dumps(build_manifest(), ensure_ascii=False, separators=(",", ":")))
