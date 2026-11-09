"""Fail when the digest-pinned browser image and npm Playwright lock diverge."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

IMAGE_PATTERN = re.compile(r"mcr\.microsoft\.com/playwright:v(?P<version>\d+\.\d+\.\d+)-noble@sha256:[0-9a-f]{64}")
JOB_PATTERN = re.compile(r"(?ms)^  browser_matrix:\s*\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\s*(?:#.*)?$|\Z)")
CONTAINER_PATTERN = re.compile(r"(?m)^    container:\s*\n(?P<body>(?:^      .*\n|^[ \t]*\n)*)")
PLAYWRIGHT_PACKAGES = (
    "node_modules/@playwright/test",
    "node_modules/playwright",
    "node_modules/playwright-core",
)


def check_playwright_image(workflow_path: Path, lockfile_path: Path) -> str:
    """Return a diagnostic on mismatch, or an empty string when versions align."""
    workflow = workflow_path.read_text(encoding="utf-8")
    job_match = JOB_PATTERN.search(workflow)
    if job_match is None:
        return "CI workflow must define jobs.browser_matrix with a digest-pinned Playwright image."
    container_matches = list(CONTAINER_PATTERN.finditer(job_match.group("body")))
    if len(container_matches) != 1:
        return "CI jobs.browser_matrix must define exactly one container.image."
    image_matches = list(re.finditer(r"(?m)^      image:\s*(?P<image>\S+)\s*$", container_matches[0].group("body")))
    if len(image_matches) != 1:
        return "CI jobs.browser_matrix.container must define exactly one image."
    match = IMAGE_PATTERN.fullmatch(image_matches[0].group("image"))
    if match is None:
        return "CI jobs.browser_matrix.container.image must use the official Playwright tag and sha256 digest."

    lockfile = json.loads(lockfile_path.read_text(encoding="utf-8"))
    packages = lockfile.get("packages", {})
    image_version = match.group("version")
    locked_versions = {
        name: packages.get(name, {}).get("version") if isinstance(packages, dict) else None
        for name in PLAYWRIGHT_PACKAGES
    }
    mismatches = {name: version for name, version in locked_versions.items() if version != image_version}
    if mismatches:
        details = ", ".join(f"{name}={version or 'missing'}" for name, version in mismatches.items())
        return (
            f"Playwright image is {image_version}, but package-lock.json has {details}. "
            "Update the image tag and verified digest together with the lockfile."
        )
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, default=Path(".github/workflows/ci.yml"))
    parser.add_argument("--lockfile", type=Path, default=Path("package-lock.json"))
    args = parser.parse_args()
    diagnostic = check_playwright_image(args.workflow, args.lockfile)
    if diagnostic:
        print(diagnostic, file=sys.stderr)
        return 1
    print("Playwright image and package-lock.json versions match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
