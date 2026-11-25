#!/usr/bin/env bash
set -euo pipefail

readonly APP_REPOSITORY="ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp"
readonly UPDATER_REPOSITORY="ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp-updater"
readonly EXPECTED_APP_LEGACY="sha256:81278d20e8dff6632a41ffd47513a0281e18daa4dbbbc0d068e0c0fd9ef1ce86"
readonly EXPECTED_UPDATER_LEGACY="sha256:6d44ebe288f85954c36e3df08c7049302ff3a0c1181b2ce91188ebcd9e95de1a"
# GET /repos/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp/actions/workflows/ci.yml
# returned this ID and path during implementation; update both if that workflow is recreated.
readonly TESTS_WORKFLOW_ID="281374633"
readonly TESTS_WORKFLOW_PATH=".github/workflows/ci.yml"
readonly PROVENANCE_KEY="io.lsf-fliegerlager.test-workflow-run-id"

fail() {
  printf 'Legacy development pointer migration: %s\n' "$*" >&2
  exit 1
}

require_equal() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" != "$expected" ]]; then
    printf '%s mismatch: expected %s, got %s.\n' "$label" "$expected" "${actual:-<empty>}" >&2
    return 1
  fi
}

[[ "${GITHUB_REF:-}" == "refs/heads/main" ]] || fail 'dispatch must target refs/heads/main.'
[[ "${GITHUB_REPOSITORY:-}" == "LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp" ]] || fail 'unexpected repository.'
[[ "${PR_NUMBER:-}" =~ ^[1-9][0-9]*$ ]] || fail 'PR_NUMBER must be a positive integer.'
[[ "${TEST_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]] || fail 'TEST_RUN_ID must be a positive integer.'
[[ "${EXPECTED_LEGACY_APP_DIGEST:-}" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'expected legacy app digest is malformed.'
[[ "${EXPECTED_LEGACY_UPDATER_DIGEST:-}" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'expected legacy updater digest is malformed.'
require_equal 'Allowlisted legacy app digest' "$EXPECTED_APP_LEGACY" "$EXPECTED_LEGACY_APP_DIGEST"
require_equal 'Allowlisted legacy updater digest' "$EXPECTED_UPDATER_LEGACY" "$EXPECTED_LEGACY_UPDATER_DIGEST"

inspect_digest() {
  local reference="$1" digest inspect_error inspect_status
  inspect_error="$(mktemp)"
  if digest="$(docker buildx imagetools inspect "$reference" --format '{{.Manifest.Digest}}' 2>"$inspect_error")"; then
    rm -f "$inspect_error"
    if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
      printf 'Registry inspect returned an invalid digest for %s: %s\n' "$reference" "${digest:-<empty>}" >&2
      return 1
    fi
    printf '%s' "$digest"
    return 0
  else
    inspect_status=$?
  fi
  if grep -Fq '404 Not Found' "$inspect_error" || grep -Fxq "ERROR: $reference: not found" "$inspect_error"; then
    rm -f "$inspect_error"
    return 44
  fi
  printf 'Registry inspect failed for %s (exit %s):\n' "$reference" "$inspect_status" >&2
  cat "$inspect_error" >&2
  rm -f "$inspect_error"
  return "$inspect_status"
}

trusted_run_id() {
  local reference="$1" manifest run_id
  if ! manifest="$(docker buildx imagetools inspect "$reference" --raw)"; then
    printf 'Could not inspect provenance manifest for %s.\n' "$reference" >&2
    return 1
  fi
  if ! run_id="$(jq -r --arg key "$PROVENANCE_KEY" '.annotations[$key] // empty' <<<"$manifest")"; then
    printf 'Could not parse workflow-run provenance for %s.\n' "$reference" >&2
    return 1
  fi
  [[ "$run_id" =~ ^[1-9][0-9]*$ ]] || {
    printf 'Missing or invalid workflow-run provenance annotation on %s.\n' "$reference" >&2
    return 1
  }
  printf '%s' "$run_id"
}

validate_source_index() {
  local repository="$1" digest="$2" expected_revision="$3" manifest run_id architectures architecture child_digest actual_revision actual_platform
  manifest="$(docker buildx imagetools inspect "$repository@$digest" --raw)" || fail "cannot inspect immutable source index $repository@$digest."
  run_id="$(jq -r --arg key "$PROVENANCE_KEY" '.annotations[$key] // empty' <<<"$manifest")" || fail "cannot parse provenance on $repository@$digest."
  require_equal "Source run ID for $repository@$digest" "$TEST_RUN_ID" "$run_id"
  if ! jq -e '
      [.manifests[] | select(.platform.os == "linux" and (.platform.architecture == "amd64" or .platform.architecture == "arm64"))]
      | length == 2
        and ([.[].platform.architecture] | sort == ["amd64", "arm64"])
        and all(.[]; .digest | test("^sha256:[0-9a-f]{64}$"))
    ' <<<"$manifest" >/dev/null; then
    fail "source index $repository@$digest must contain exactly one linux/amd64 and one linux/arm64 image."
  fi
  architectures="$(jq -r '.manifests[] | select(.platform.os == "linux" and (.platform.architecture == "amd64" or .platform.architecture == "arm64")) | [.platform.architecture, .digest] | @tsv' <<<"$manifest")"
  while IFS=$'\t' read -r architecture child_digest; do
    docker pull --platform "linux/$architecture" "$repository@$child_digest" >/dev/null || fail "cannot pull $architecture source image $repository@$child_digest."
    actual_platform="$(docker image inspect "$repository@$child_digest" --format '{{.Os}}/{{.Architecture}}')" || fail "cannot inspect $architecture source platform for $repository@$child_digest."
    require_equal "Source platform for $repository @$child_digest" "linux/$architecture" "$actual_platform"
    actual_revision="$(docker image inspect "$repository@$child_digest" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" || fail "cannot inspect $architecture source labels for $repository@$child_digest."
    require_equal "Source revision for $repository linux/$architecture" "$expected_revision" "$actual_revision"
  done <<<"$architectures"
}

read_current_pr() {
  local response
  response="$(gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER")" || fail "cannot read PR #$PR_NUMBER."
  jq -e --arg repository "$GITHUB_REPOSITORY" --arg revision "$REVISION" '
    .state == "open"
    and .head.repo.full_name == $repository
    and .head.sha == $revision
  ' <<<"$response" >/dev/null || fail "PR #$PR_NUMBER must be open, same-repository, and still at tested SHA $REVISION."
}

[[ "${GH_TOKEN:-}" != "" ]] || fail 'GH_TOKEN is required for read-only GitHub validation.'

test_run="$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$TEST_RUN_ID")" || fail "cannot read Tests run $TEST_RUN_ID."
jq -e --argjson workflow_id "$TESTS_WORKFLOW_ID" --arg workflow_path "$TESTS_WORKFLOW_PATH" --arg repository "$GITHUB_REPOSITORY" --arg pr_number "$PR_NUMBER" '
  .workflow_id == $workflow_id
  and .path == $workflow_path
  and .status == "completed"
  and .conclusion == "success"
  and .event == "pull_request"
  and .run_attempt == 1
  and .head_repository.full_name == $repository
  and (.head_sha | type == "string" and test("^[0-9a-f]{40}$"))
  and any(.pull_requests[]?; (.number | tostring) == $pr_number)
' <<<"$test_run" >/dev/null || fail "run $TEST_RUN_ID must be successful attempt 1 of the trusted Tests workflow for this same-repository PR."
REVISION="$(jq -r '.head_sha' <<<"$test_run")"
read_current_pr

CURRENT_APP_DEV_DIGEST="$(inspect_digest "$APP_REPOSITORY:dev")" || fail 'cannot inspect current app dev pointer.'
CURRENT_UPDATER_DEV_DIGEST="$(inspect_digest "$UPDATER_REPOSITORY:dev")" || fail 'cannot inspect current updater dev pointer.'
require_equal 'Current app legacy pointer' "$EXPECTED_LEGACY_APP_DIGEST" "$CURRENT_APP_DEV_DIGEST"
require_equal 'Current updater legacy pointer' "$EXPECTED_LEGACY_UPDATER_DIGEST" "$CURRENT_UPDATER_DEV_DIGEST"

APP_SOURCE_TAG="$APP_REPOSITORY:dev-$PR_NUMBER-$REVISION"
UPDATER_SOURCE_TAG="$UPDATER_REPOSITORY:dev-$PR_NUMBER-$REVISION"
APP_SOURCE_DIGEST="$(inspect_digest "$APP_SOURCE_TAG")" || fail "cannot inspect tested app source tag $APP_SOURCE_TAG."
UPDATER_SOURCE_DIGEST="$(inspect_digest "$UPDATER_SOURCE_TAG")" || fail "cannot inspect tested updater source tag $UPDATER_SOURCE_TAG."
APP_SOURCE_RUN_ID="$(trusted_run_id "$APP_REPOSITORY@$APP_SOURCE_DIGEST")" || fail 'app source lacks trusted run provenance.'
UPDATER_SOURCE_RUN_ID="$(trusted_run_id "$UPDATER_REPOSITORY@$UPDATER_SOURCE_DIGEST")" || fail 'updater source lacks trusted run provenance.'
require_equal 'App source workflow-run ID' "$TEST_RUN_ID" "$APP_SOURCE_RUN_ID"
require_equal 'Updater source workflow-run ID' "$TEST_RUN_ID" "$UPDATER_SOURCE_RUN_ID"
validate_source_index "$APP_REPOSITORY" "$APP_SOURCE_DIGEST" "$REVISION"
validate_source_index "$UPDATER_REPOSITORY" "$UPDATER_SOURCE_DIGEST" "$REVISION"

# Recheck the PR and old pair immediately before writes. GitHub serializes this
# job with normal dev promotion; the digest checks also detect unexpected edits.
read_current_pr
CURRENT_APP_DEV_DIGEST="$(inspect_digest "$APP_REPOSITORY:dev")" || fail 'cannot re-inspect current app dev pointer before promotion.'
CURRENT_UPDATER_DEV_DIGEST="$(inspect_digest "$UPDATER_REPOSITORY:dev")" || fail 'cannot re-inspect current updater dev pointer before promotion.'
require_equal 'App dev pointer before migration' "$EXPECTED_LEGACY_APP_DIGEST" "$CURRENT_APP_DEV_DIGEST"
require_equal 'Updater dev pointer before migration' "$EXPECTED_LEGACY_UPDATER_DIGEST" "$CURRENT_UPDATER_DEV_DIGEST"

restore_legacy_pair() {
  local failed=0 restored_app restored_updater
  docker buildx imagetools create --tag "$APP_REPOSITORY:dev" "$APP_REPOSITORY@$EXPECTED_APP_LEGACY" || failed=1
  docker buildx imagetools create --tag "$UPDATER_REPOSITORY:dev" "$UPDATER_REPOSITORY@$EXPECTED_UPDATER_LEGACY" || failed=1
  restored_app="$(inspect_digest "$APP_REPOSITORY:dev")" || failed=1
  restored_updater="$(inspect_digest "$UPDATER_REPOSITORY:dev")" || failed=1
  [[ "${restored_app:-}" == "$EXPECTED_APP_LEGACY" ]] || failed=1
  [[ "${restored_updater:-}" == "$EXPECTED_UPDATER_LEGACY" ]] || failed=1
  return "$failed"
}

recover_failed_migration() {
  local status=$?
  trap - EXIT INT TERM
  if ! restore_legacy_pair; then
    printf 'Legacy dev pointer recovery failed; repair the pair manually. Expected app=%s updater=%s\n' "$EXPECTED_APP_LEGACY" "$EXPECTED_UPDATER_LEGACY" >&2
  fi
  exit "$status"
}

trap recover_failed_migration EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker buildx imagetools create --tag "$APP_REPOSITORY:dev" "$APP_REPOSITORY@$APP_SOURCE_DIGEST"
docker buildx imagetools create --tag "$UPDATER_REPOSITORY:dev" "$UPDATER_REPOSITORY@$UPDATER_SOURCE_DIGEST"
FINAL_APP_DEV_DIGEST="$(inspect_digest "$APP_REPOSITORY:dev")"
FINAL_UPDATER_DEV_DIGEST="$(inspect_digest "$UPDATER_REPOSITORY:dev")"
require_equal 'Final app dev digest' "$APP_SOURCE_DIGEST" "$FINAL_APP_DEV_DIGEST"
require_equal 'Final updater dev digest' "$UPDATER_SOURCE_DIGEST" "$FINAL_UPDATER_DEV_DIGEST"
trap - EXIT INT TERM
printf 'Migrated dev pointers to tested PR #%s, SHA %s, Tests run %s.\n' "$PR_NUMBER" "$REVISION" "$TEST_RUN_ID"
