#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_DIR = ROOT / "changelog"


def git_output(*args: str) -> str:
    """Run git and return stripped stdout."""
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def last_revision_for(path: Path) -> str:
    """Return the mainline commit that introduced a changelog file, following renames."""
    output = git_output("log", "--follow", "--first-parent", "--format=%H", "--", str(path.relative_to(ROOT)))
    revisions = output.splitlines()
    return revisions[-1] if revisions else "unknown"


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


def _render(entries: list[dict[str, str]]) -> str:
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":")) + "\n"


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """Return the longest prefix of value that fits in max_bytes when encoded."""
    return value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def _fit_oversized_entry(entry: dict[str, str], max_bytes: int) -> dict[str, str]:
    """Truncate an oversized entry body without splitting a UTF-8 code point."""
    candidate = dict(entry)
    body = candidate["body"]
    low, high = 0, len(body.encode("utf-8"))
    while low < high:
        body_bytes = (low + high + 1) // 2
        candidate["body"] = _truncate_utf8(body, body_bytes)
        if len(_render([candidate]).encode("utf-8")) <= max_bytes:
            low = body_bytes
        else:
            high = body_bytes - 1

    candidate["body"] = _truncate_utf8(body, low)
    if len(_render([candidate]).encode("utf-8")) > max_bytes:
        candidate["body"] = ""
    if len(_render([candidate]).encode("utf-8")) > max_bytes:
        raise ValueError("max_bytes is too small for the changelog entry metadata")
    return candidate


def render_bounded_manifest(max_bytes: int) -> str:
    """Render the newest changelog entries within an inclusive UTF-8 byte budget."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    selected: list[dict[str, str]] = []
    for entry in reversed(build_manifest()):
        candidate = [entry, *selected]
        if len(_render(candidate).encode("utf-8")) <= max_bytes:
            selected = candidate
        elif not selected:
            selected = [_fit_oversized_entry(entry, max_bytes)]
        else:
            break

    return _render(selected)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-bytes", type=int)
    args = parser.parse_args()
    output = render_bounded_manifest(args.max_bytes) if args.max_bytes is not None else _render(build_manifest())
    print(output, end="")
