from pathlib import Path

from scripts import build_changelog_manifest


def test_build_manifest_adds_first_parent_version(monkeypatch, tmp_path: Path):
    changelog_dir = tmp_path / "changelog"
    changelog_dir.mkdir()
    entry_path = changelog_dir / "pr-1-example.md"
    entry_path.write_text("# Example\n\nDetails", encoding="utf-8")

    monkeypatch.setattr(build_changelog_manifest, "ROOT", tmp_path)
    monkeypatch.setattr(build_changelog_manifest, "CHANGELOG_DIR", changelog_dir)
    monkeypatch.setattr(build_changelog_manifest, "last_revision_for", lambda _path: "rev2")
    monkeypatch.setattr(build_changelog_manifest, "revision_versions", lambda: {"rev2": 2})

    assert build_changelog_manifest.build_manifest() == [
        {
            "version": "2",
            "revision": "rev2",
            "path": "changelog/pr-1-example.md",
            "title": "Example",
            "body": "Details",
        }
    ]


def test_docker_workflow_uses_first_parent_version():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "docker.yml").read_text(encoding="utf-8")

    assert (
        "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7\n        with:\n          fetch-depth: 0"
    ) in workflow
    assert 'echo "version=$(git rev-list --first-parent --count HEAD)"' in workflow
    assert workflow.count("APP_VERSION=${{ steps.metadata.outputs.version }}") == 2


RESOURCE_INTENSIVE_WORKFLOWS = ("ci.yml", "docker.yml", "security.yml", "dast.yml")
CONCURRENCY_GROUP = (
    "${{ github.workflow }}-${{ github.event_name }}-${{ github.event.pull_request.number || github.ref }}"
)


def test_resource_intensive_workflows_isolate_concurrency_contexts():
    workflows_dir = Path(__file__).parents[1] / ".github" / "workflows"

    for workflow_name in RESOURCE_INTENSIVE_WORKFLOWS:
        workflow = (workflows_dir / workflow_name).read_text(encoding="utf-8")
        assert f"concurrency:\n  group: {CONCURRENCY_GROUP}\n  cancel-in-progress: true" in workflow


def test_playwright_system_dependencies_are_documented_as_uncacheable():
    readme = (Path(__file__).parents[1] / ".github" / "workflows" / "README.md").read_text(encoding="utf-8")

    assert "Systemabhängigkeiten" in readme
    assert "nicht gecacht" in readme
    assert "stale" in readme
    assert "install-deps" in readme
