import json
import os
import subprocess
import sys
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
    assert text.count("docker load") == 4
    assert "docker push" in text
    assert "docker/build-push-action@" not in text
    assert "actions/checkout@" not in text
    publish = next(step for step in job["steps"] if step.get("name") == "Publish tested development images")
    assert "linux-amd64" in publish["run"]
    assert "linux-arm64" in publish["run"]
    assert publish["run"].count("docker buildx imagetools create") >= 2
    assert "ensure_immutable_tag" in publish["run"]
    assert "404 Not Found" in publish["run"]
    promotion = next(step for step in job["steps"] if step.get("name") == "Promote newest development revision")
    assert promotion["env"]["TEST_RUN_ID"] == "${{ github.event.workflow_run.id }}"
    assert "org.opencontainers.image.created" not in promotion["run"]
    assert "io.lsf-fliegerlager.test-workflow-run-id" in promotion["run"]
    assert "docker buildx imagetools inspect" in promotion["run"]
    assert "^[1-9][0-9]*$" in promotion["run"]
    assert promotion["run"].count("--annotation") == 0
    assert "trusted_run_id" in promotion["run"]
    assert ':dev"' in promotion["run"]
    test_job = workflow["jobs"]["docker-test"]
    artifact_build = next(
        step for step in test_job["steps"] if step.get("name") == "Export PR multi-architecture images"
    )
    assert artifact_build["run"].count("docker save") == 2
    assert "--platform linux/arm64" in artifact_build["run"]
    assert "{{.Architecture}}" in artifact_build["run"]
    assert artifact_build["run"].count("docker buildx build") == 2
    assert "app-linux-amd64.tar" in artifact_build["run"]
    assert "app-linux-arm64.tar" in artifact_build["run"]
    assert "updater-linux-amd64.tar" in artifact_build["run"]
    assert "updater-linux-arm64.tar" in artifact_build["run"]
    assert "type=docker,dest=" in artifact_build["run"]
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
    assert '"staging-$TESTED_SHA"' in text
    assert "latest" in text
    assert text.count("docker/build-push-action@") == 2
    assert sum(step.get("with", {}).get("push") == "true" for step in job["steps"]) == 2
    build_steps = [step for step in job["steps"] if "docker/build-push-action@" in step.get("uses", "")]
    assert all("github.run_id" in step["with"]["tags"] for step in build_steps)
    assert all("staging-${{ github.event.workflow_run.head_sha }}" not in step["with"]["tags"] for step in build_steps)
    immutable = next(step for step in job["steps"] if step.get("name") == "Publish immutable revision tags")
    assert immutable["run"].count("ensure_immutable_tag") >= 3
    assert "404 Not Found" in immutable["run"]
    assert "already exists with digest" in immutable["run"]


def test_container_build_dates_are_deterministic_for_the_tested_commit() -> None:
    workflow = _docker_workflow()

    for job_name in ("docker-test", "docker-publish"):
        metadata = next(
            step for step in workflow["jobs"][job_name]["steps"] if step.get("name") == "Read build metadata"
        )
        assert "git show -s --format=%cI HEAD" in metadata["run"]
        assert "date -u" not in metadata["run"]


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
    assert "ensure_immutable_tag" in text
    assert "404 Not Found" in text


def test_prod_checkout_is_bound_to_dispatch_commit_and_main_only() -> None:
    workflow = _release_workflow()
    job = workflow["jobs"]["promote-prod"]

    assert "github.ref == 'refs/heads/main'" in job["if"]
    checkout = next(step for step in job["steps"] if step.get("name") == "Checkout protected main branch")
    assert checkout["with"]["ref"] == "${{ github.sha }}"


def test_dev_inspection_fails_closed_except_for_an_explicit_404() -> None:
    workflow = _docker_workflow()
    job = workflow["jobs"]["docker-publish-dev"]
    promotion = next(step for step in job["steps"] if step.get("name") == "Promote newest development revision")
    script = promotion["run"]

    assert "inspect_status=$?" in script
    assert "404 Not Found" in script
    assert 'cat "$inspect_error" >&2' in script
    assert 'return "$inspect_status"' in script


def test_prod_promotion_restores_both_previous_pointers_and_verifies_the_pair() -> None:
    workflow = _release_workflow()
    job = workflow["jobs"]["promote-prod"]
    promotion = next(step for step in job["steps"] if step.get("name") == "Promote production image pair")
    script = promotion["run"]

    assert "PREVIOUS_APP_PROD_DIGEST" in script
    assert "PREVIOUS_UPDATER_PROD_DIGEST" in script
    assert "restore_previous_prod_pair" in script
    restore_body = script.split("restore_previous_prod_pair()", 1)[1].split("}", 1)[0]
    assert restore_body.count("docker buildx imagetools create") == 2
    assert "FINAL_APP_PROD_DIGEST" in script
    assert "FINAL_UPDATER_PROD_DIGEST" in script
    assert 'test "$FINAL_APP_PROD_DIGEST" = "$APP_DIGEST"' in script
    assert 'test "$FINAL_UPDATER_PROD_DIGEST" = "$UPDATER_DIGEST"' in script
    assert script.count("restore_previous_prod_pair") >= 2


@pytest.mark.parametrize(
    "failure",
    [
        "",
        "app-before",
        "updater-before",
        "updater-after",
        "conflict",
        "inspection",
        "bootstrap",
        "partial",
        "idempotent",
    ],
)
def test_production_promotion_executes_pair_recovery(tmp_path, failure):
    """Exercise the actual workflow shell against a fake registry CLI boundary."""
    revision = "a" * 40
    app = "ghcr.io/example/app"
    updater = "ghcr.io/example/updater"
    old_app, old_updater = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    new_app, new_updater = "sha256:" + "3" * 64, "sha256:" + "4" * 64
    state = {
        "tags": {
            f"{app}:latest": new_app,
            f"{updater}:latest": new_updater,
            f"{app}:prod": old_app,
            f"{updater}:prod": old_updater,
        },
        "writes": [],
        "failed": False,
    }
    if failure == "conflict":
        state["tags"][f"{updater}:prod-{revision}"] = old_updater
    if failure in {"bootstrap", "partial"}:
        del state["tags"][f"{app}:prod"]
    if failure == "bootstrap":
        del state["tags"][f"{updater}:prod"]
    if failure == "idempotent":
        state["tags"][f"{app}:prod-{revision}"] = new_app
        state["tags"][f"{updater}:prod-{revision}"] = new_updater
    state_path = tmp_path / "registry.json"
    state_path.write_text(json.dumps(state))
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, sys
from pathlib import Path
path = Path(os.environ["FAKE_REGISTRY"])
state = json.loads(path.read_text())
args = sys.argv[1:]
failure = os.environ["FAILURE"]
if args[:3] == ["buildx", "imagetools", "inspect"]:
    reference = args[3]
    if failure == "inspection" and reference.endswith(":prod"):
        print("401 Unauthorized", file=sys.stderr)
        sys.exit(1)
    if reference not in state["tags"]:
        print("404 Not Found", file=sys.stderr)
        sys.exit(1)
    print(state["tags"][reference])
elif args[:2] == ["image", "inspect"]:
    print("a" * 40)
elif args[:3] == ["buildx", "imagetools", "create"]:
    tag = args[args.index("--tag") + 1]
    digest = args[-1].split("@", 1)[1]
    should_fail = (not state["failed"] and tag.endswith(":prod") and
                   ((failure == "app-before" and "/app:" in tag) or
                    (failure.startswith("updater-") and "/updater:" in tag)))
    if not should_fail or failure.endswith("after"):
        state["tags"][tag] = digest
        state["writes"].append([tag, digest])
    if should_fail:
        state["failed"] = True
    path.write_text(json.dumps(state))
    if should_fail:
        sys.exit(1)
elif args[:1] != ["pull"]:
    sys.exit(2)
"""
    )
    docker.chmod(0o755)
    steps = _release_workflow()["jobs"]["promote-prod"]["steps"]
    script = next(step["run"] for step in steps if step.get("name") == "Promote production image pair")
    result = subprocess.run(
        ["bash"],
        input=f"git() {{ printf '%s' '{revision}'; }}\n" + script,
        text=True,
        capture_output=True,
        timeout=10,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "FAKE_REGISTRY": str(state_path),
            "FAILURE": failure,
            "REGISTRY": "ghcr.io/example",
            "APP": "app",
            "UPDATER": "updater",
        },
    )
    final = json.loads(state_path.read_text())
    succeeded = failure in {"", "bootstrap", "idempotent"}
    assert result.returncode == (0 if succeeded else 1), result.stderr
    assert final["tags"].get(f"{app}:prod") == (new_app if succeeded else None if failure == "partial" else old_app)
    assert final["tags"][f"{updater}:prod"] == (new_updater if succeeded else old_updater)
    if failure in {"conflict", "inspection", "partial"}:
        assert not any(tag.endswith(":prod") for tag, _digest in final["writes"])
    if failure == "idempotent":
        assert all(tag.endswith(":prod") for tag, _digest in final["writes"])


@pytest.mark.parametrize(
    "failure",
    [
        "",
        "second-promotion",
        "final-digest",
        "newer",
        "both-missing",
        "one-missing",
        "unauthorized",
        "timeout",
        "missing-annotation",
        "invalid-annotation",
        "mismatched-pair-runs",
        "source-mismatch",
    ],
)
def test_dev_promotion_executes_pair_recovery(tmp_path: Path, failure: str) -> None:
    app = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp"
    updater = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp-updater"
    old_app, old_updater = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    new_app, new_updater = "sha256:" + "3" * 64, "sha256:" + "4" * 64
    old_run = "20" if failure == "newer" else "10"
    updater_run = "11" if failure == "mismatched-pair-runs" else old_run
    app_source_run = "9" if failure == "source-mismatch" else "10"
    state = {
        "tags": {
            f"{app}:dev": old_app,
            f"{updater}:dev": old_updater,
            f"{app}:dev-618-{'a' * 40}": new_app,
            f"{updater}:dev-618-{'a' * 40}": new_updater,
        },
        "annotations": {old_app: old_run, old_updater: updater_run, new_app: app_source_run, new_updater: "10"},
        "writes": [],
        "promotions": 0,
        "final_mismatch_used": False,
    }
    if failure == "missing-annotation":
        del state["annotations"][old_app]
    if failure == "invalid-annotation":
        state["annotations"][old_app] = "invalid"
    if failure in {"both-missing", "one-missing"}:
        del state["tags"][f"{app}:dev"]
    if failure == "both-missing":
        del state["tags"][f"{updater}:dev"]
    state_path = tmp_path / "registry.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, sys
from pathlib import Path
path = Path(os.environ["FAKE_REGISTRY"])
state = json.loads(path.read_text())
args = sys.argv[1:]
if args[:3] == ["buildx", "imagetools", "inspect"]:
    ref = args[3]
    if os.environ["FAILURE"] in {"unauthorized", "timeout"} and ref.endswith(":dev"):
        message = "401 Unauthorized" if os.environ["FAILURE"] == "unauthorized" else "connection timeout"
        print(message, file=sys.stderr)
        sys.exit(1)
    digest = ref.split("@", 1)[1] if "@" in ref else state["tags"].get(ref)
    if digest is None:
        print("404 Not Found", file=sys.stderr); sys.exit(1)
    if "--raw" in args:
        annotation = state["annotations"].get(digest)
        annotations = {} if annotation is None else {"io.lsf-fliegerlager.test-workflow-run-id": annotation}
        print(json.dumps({"annotations": annotations}))
    else:
        if (
            os.environ["FAILURE"] == "final-digest"
            and ref.endswith(":dev")
            and state["promotions"] == 2
            and not state["final_mismatch_used"]
        ):
            state["final_mismatch_used"] = True
            path.write_text(json.dumps(state))
            print("sha256:" + "9" * 64)
            sys.exit(0)
        print(digest)
elif args[:3] == ["buildx", "imagetools", "create"]:
    tag = args[args.index("--tag") + 1]
    digest = args[-1].split("@", 1)[1]
    is_target = tag.endswith(":dev")
    if is_target:
        state["promotions"] += 1
        if os.environ["FAILURE"] == "second-promotion" and state["promotions"] == 2:
            state["writes"].append([tag, digest]); state["tags"][tag] = digest
            path.write_text(json.dumps(state)); sys.exit(1)
    state["tags"][tag] = digest
    state["writes"].append([tag, digest])
    path.write_text(json.dumps(state))
else:
    sys.exit(2)
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    steps = _docker_workflow()["jobs"]["docker-publish-dev"]["steps"]
    script = next(step["run"] for step in steps if step.get("name") == "Promote newest development revision")
    result = subprocess.run(
        ["bash"],
        input=script,
        text=True,
        capture_output=True,
        timeout=10,
        env={
            **os.environ,
            "TEST_RUN_ID": "10",
            "PR_NUMBER": "618",
            "REVISION": "a" * 40,
            "FAKE_REGISTRY": str(state_path),
            "FAILURE": failure,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
    )
    final = json.loads(state_path.read_text(encoding="utf-8"))
    successful = failure in {"", "both-missing", "newer"}
    assert result.returncode == (0 if successful else 1), result.stderr
    if failure == "newer":
        assert final["tags"][f"{app}:dev"] == old_app
        assert final["tags"][f"{updater}:dev"] == old_updater
    elif successful:
        assert final["tags"][f"{app}:dev"] == new_app
        assert final["tags"][f"{updater}:dev"] == new_updater
    elif failure == "one-missing":
        assert f"{app}:dev" not in final["tags"]
        assert final["tags"][f"{updater}:dev"] == old_updater
        assert final["writes"] == []
    else:
        assert final["tags"][f"{app}:dev"] == old_app
        assert final["tags"][f"{updater}:dev"] == old_updater


def test_dev_pair_guard_rejects_missing_half_and_restores_after_second_write() -> None:
    steps = _docker_workflow()["jobs"]["docker-publish-dev"]["steps"]
    promotion = next(step for step in steps if step.get("name") == "Promote newest development revision")
    script = promotion["run"]
    assert "restore_previous_dev_pair" in script
    assert "PREVIOUS_APP_DEV_DIGEST" in script
    assert "PREVIOUS_UPDATER_DEV_DIGEST" in script
    assert "FINAL_APP_DEV_DIGEST" in script
    assert "FINAL_UPDATER_DEV_DIGEST" in script
    assert script.count("--annotation") == 0
    assert 'trusted_run_id "$APP_REPOSITORY@$PREVIOUS_APP_DEV_DIGEST"' in script
    assert 'trusted_run_id "$UPDATER_REPOSITORY@$PREVIOUS_UPDATER_DEV_DIGEST"' in script


def test_prod_workflow_serializes_complete_image_pair_promotions() -> None:
    workflow = _release_workflow()

    assert workflow["concurrency"] == {
        "group": "production-image-promotion",
        "cancel-in-progress": "false",
    }


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


def test_default_migration_manifest_includes_all_installed_migrated_apps(monkeypatch) -> None:
    from scripts import build_migration_manifest

    monkeypatch.syspath_prepend(str(ROOT / "src"))
    paths = build_migration_manifest.installed_migration_paths()
    rendered = build_migration_manifest.render_manifest(paths)
    identifiers = {entry["identifier"] for entry in yaml.safe_load(rendered)["migrations"]}

    assert "billing.0001_initial" in identifiers
    assert "auth.0001_initial" in identifiers
    assert "contenttypes.0001_initial" in identifiers
    assert "sessions.0001_initial" in identifiers


def test_docker_metadata_jobs_install_django_before_building_migration_manifest() -> None:
    workflow = _docker_workflow()

    for job_name in ("docker-test", "docker-publish"):
        steps = workflow["jobs"][job_name]["steps"]
        names = [step.get("name") for step in steps]
        metadata_index = names.index("Read build metadata")
        assert names.index("Setup Python") < metadata_index
        assert names.index("Install migration manifest dependencies") < metadata_index
        install = next(step for step in steps if step.get("name") == "Install migration manifest dependencies")
        assert install["run"] == "pip install -r requirements.txt"
