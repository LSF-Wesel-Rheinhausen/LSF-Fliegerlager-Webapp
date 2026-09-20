from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def _release_workflow() -> dict:
    return yaml.load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def _docker_workflow() -> dict:
    return yaml.load(
        (ROOT / ".github/workflows/docker.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def test_pull_request_release_publishes_only_tested_same_repo_dev_tags() -> None:
    workflow = _docker_workflow()
    job = workflow["jobs"]["docker-publish-dev"]

    assert set(workflow["on"]) == {"pull_request", "workflow_run"}
    assert job["needs"] == "docker-test"
    assert "needs.docker-test.result == 'success'" in job["if"]
    assert "github.event_name == 'workflow_run'" in job["if"]
    assert "github.event.workflow_run.event == 'pull_request'" in job["if"]
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in job["if"]
    text = str(job)
    assert "dev-$PR_NUMBER-$REVISION" in text
    assert "github.event.pull_request.head.sha" not in text
    assert "docker load" in text
    assert "docker push" in text
    assert "docker/build-push-action@" not in text
    assert "actions/checkout@" not in text
    promotion = next(step for step in job["steps"] if step.get("name") == "Promote newest development revision")
    assert "CANDIDATE_CREATED" in promotion["run"]
    assert "docker image inspect lsf-webapp:test" in promotion["run"]
    assert "CURRENT_CREATED" in promotion["run"]
    assert ':dev"' in promotion["run"]
    test_job = workflow["jobs"]["docker-test"]
    assert "docker save" in str(test_job)
    assert "actions/upload-artifact@" in str(test_job)


def test_pr_controlled_workflow_never_receives_package_write_token() -> None:
    workflow = _docker_workflow()
    test_job = workflow["jobs"]["docker-test"]
    assert "github.event_name == 'pull_request'" in test_job["if"]
    assert "github.event.pull_request.head.repo.full_name != github.repository" not in test_job["if"]
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in test_job["if"]
    assert "github.event.pull_request.number" in test_job["concurrency"]["group"]
    assert "github.event_name == 'workflow_run'" in workflow["jobs"]["docker-publish-dev"]["if"]
    for job in workflow["jobs"].values():
        condition = str(job.get("if", ""))
        if "github.event_name == 'pull_request'" in condition:
            assert job.get("permissions", {}).get("packages") != "write"
            assert "secrets.GITHUB_TOKEN" not in str(job)


def test_main_release_builds_staging_sha_and_latest_without_rebuilding_for_latest() -> None:
    workflow = _docker_workflow()
    job = workflow["jobs"]["docker-publish"]
    text = str(job)

    assert "workflow_run" in workflow["on"]
    assert "staging-${{ github.event.workflow_run.head_sha }}" in text
    assert "latest" in text
    assert text.count("docker/build-push-action@") == 2
    assert sum(step.get("with", {}).get("push") == "true" for step in job["steps"]) == 2


def test_prod_workflow_promotes_matching_existing_digests_and_rejects_mixed_revisions() -> None:
    workflow = _release_workflow()
    job = workflow["jobs"]["promote-prod"]
    text = str(job)

    assert "workflow_dispatch" in workflow["on"]
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert job["environment"] == "production"
    assert any("docker/login-action@" in step.get("uses", "") for step in job["steps"])
    assert "docker buildx imagetools create" in text
    assert "prod-$APP_REVISION" in text
    assert "prod-$UPDATER_REVISION" in text
    assert "prod" in text
    assert "$REGISTRY/$APP:latest" in text
    assert "$REGISTRY/$UPDATER:latest" in text
    assert "revision" not in workflow["on"]["workflow_dispatch"]
    assert "APP_REVISION" in text
    assert "UPDATER_REVISION" in text
    assert 'test "$APP_REVISION" = "$UPDATER_REVISION"' in text
    assert 'docker pull --platform linux/amd64 "$REGISTRY/$APP@$APP_DIGEST"' in text
    assert 'docker pull --platform linux/amd64 "$REGISTRY/$UPDATER@$UPDATER_DIGEST"' in text
    assert 'docker image inspect "$REGISTRY/$APP@$APP_DIGEST"' in text
    assert 'docker image inspect "$REGISTRY/$UPDATER@$UPDATER_DIGEST"' in text
    assert "docker/build-push-action@" not in text
    assert '--tag "$REGISTRY/$APP:latest"' not in text
    assert '--tag "$REGISTRY/$UPDATER:latest"' not in text


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.updater"])
def test_images_expose_shared_revision_build_and_migration_labels(dockerfile: str) -> None:
    content = (ROOT / dockerfile).read_text(encoding="utf-8")

    assert "ARG APP_REVISION=unknown" in content
    assert "ARG APP_BUILD_DATE=unknown" in content
    assert 'org.opencontainers.image.revision="${APP_REVISION}"' in content
    assert 'io.lsf-fliegerlager.migrations="${MIGRATION_MANIFEST}"' in content


def test_migration_manifest_is_deterministic_and_contains_required_contract() -> None:
    from scripts import build_migration_manifest

    rendered = build_migration_manifest.render_manifest(
        [
            ROOT / "src/billing/migrations/0001_initial.py",
            ROOT / "src/billing/migrations/0002_camp_foerdersatz_charge_foerderfaehig_and_more.py",
        ]
    )
    payload = yaml.safe_load(rendered)

    migrations = payload["migrations"]
    assert migrations[0]["identifier"] == "billing.0001_initial"
    assert migrations[0]["dependencies"] == []
    assert migrations[0]["reversible"] is True
    assert migrations[1]["identifier"] == "billing.0002_camp_foerdersatz_charge_foerderfaehig_and_more"
    assert migrations[1]["dependencies"] == ["billing.0001_initial"]
    assert migrations[1]["reversible"] is True
    assert payload["files"][0]["path"] < payload["files"][1]["path"]
    assert all(len(item["sha256"]) == 64 for item in payload["files"])
    assert rendered == build_migration_manifest.render_manifest(
        list(
            reversed(
                [
                    ROOT / "src/billing/migrations/0001_initial.py",
                    ROOT / "src/billing/migrations/0002_camp_foerdersatz_charge_foerderfaehig_and_more.py",
                ]
            )
        )
    )


def test_migration_manifest_marks_runpython_without_reverse_as_irreversible(tmp_path: Path) -> None:
    from scripts import build_migration_manifest

    migration = tmp_path / "0001_seed.py"
    migration.write_text(
        "from django.db import migrations\n"
        "class Migration(migrations.Migration):\n"
        "    dependencies = []\n"
        "    operations = [migrations.RunPython(seed)]\n",
        encoding="utf-8",
    )

    payload = yaml.safe_load(build_migration_manifest.render_manifest([migration]))

    assert payload["migrations"][0]["reversible"] is False
