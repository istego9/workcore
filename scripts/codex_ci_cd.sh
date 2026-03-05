#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW_CI="ci.yml"
WORKFLOW_DEPLOY="deploy-azure.yml"

log() {
  printf '[codex-ci-cd] %s\n' "$*"
}

fail() {
  printf '[codex-ci-cd] error: %s\n' "$*" >&2
  exit 1
}

run_cmd() {
  log ">> $*"
  "$@"
}

require_gh() {
  if ! command -v gh >/dev/null 2>&1; then
    fail "GitHub CLI (gh) is not installed"
  fi
  if ! gh auth status >/dev/null 2>&1; then
    fail "GitHub CLI is not authenticated. Run: gh auth login"
  fi
}

normalize_bool() {
  local raw="${1:-}"
  case "$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')" in
    true|false)
      printf '%s' "$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')"
      ;;
    1|yes|y|on)
      printf 'true'
      ;;
    0|no|n|off)
      printf 'false'
      ;;
    *)
      fail "invalid boolean value: '${raw}'"
      ;;
  esac
}

usage() {
  cat <<'EOF'
Usage:
  ./scripts/codex_ci_cd.sh doctor
  ./scripts/codex_ci_cd.sh ci-local [--with-builder-e2e] [--with-dev-check]
  ./scripts/codex_ci_cd.sh deploy-azure [options]
  ./scripts/codex_ci_cd.sh runs [ci|deploy|all] [--limit N]
  ./scripts/codex_ci_cd.sh watch <run-id>
  ./scripts/codex_ci_cd.sh view <run-id> [--log]
  ./scripts/codex_ci_cd.sh cancel <run-id>

Commands:
  doctor
      Check local prerequisites for Codex CI/CD usage.

  ci-local
      Run local checks aligned with merge gates:
      - ./scripts/archctl_validate.sh
      - ./.venv/bin/python -m pytest apps/orchestrator/tests
      - cd apps/builder && npm run test:unit
      Optional:
      - --with-builder-e2e: cd apps/builder && npm run test:e2e
      - --with-dev-check: ./scripts/dev_check.sh

  deploy-azure
      Dispatch GitHub workflow deploy-azure.yml via gh CLI.
      Options:
        --ref <git-ref>                                (default: main)
        --resource-group <name>                        (default: rg-workcore-prod-uaen)
        --location <azure-region>                      (default: uaenorth)
        --deploy-frontdoor <true|false>                (default: true)
        --deploy-apim <true|false>                     (default: true)
        --deploy-builder-ui <true|false>               (default: true)
        --swa-allow-insecure-tls-download <true|false> (default: false)
        --configure-ui-entra-auth <true|false>         (default: false)
        --create-entra-app-registration <true|false>   (default: false)
        --entra-app-name <name>                        (default: workcore-builder-swa)
        --enable-secondary-api-domain <true|false>     (default: false)
        --workcore-domain <domain>                     (default: "")
        --api-primary-domain <domain>                  (default: api.hq21.tech)
        --api-secondary-domain <domain>                (default: api.runwcr.com)
        --chatkit-domain <domain>                      (default: "")
        --cors-allow-origins "<csv>"                   (default: "")
        --integration-http-allowed-hosts "<csv>"       (default: "")
        --wait                                          Wait for run completion (gh run watch --exit-status)

  runs
      List recent GitHub Actions runs.
      Target:
        ci      -> ci.yml
        deploy  -> deploy-azure.yml
        all     -> all workflows (default)
      Options:
        --limit N (default: 10)

  watch <run-id>
      Block until run completes; exits non-zero on failed run.

  view <run-id> [--log]
      Show run summary; with --log prints job logs.

  cancel <run-id>
      Cancel a running workflow.
EOF
}

doctor() {
  log "workspace: ${ROOT_DIR}"

  if command -v gh >/dev/null 2>&1; then
    gh --version | head -n 1
    if gh auth status >/dev/null 2>&1; then
      log "gh auth: ok"
    else
      log "gh auth: missing (run 'gh auth login')"
    fi
  else
    log "gh: not found"
  fi

  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    "${ROOT_DIR}/.venv/bin/python" --version
  else
    log ".venv python: not found at ${ROOT_DIR}/.venv/bin/python"
  fi

  if command -v npm >/dev/null 2>&1; then
    npm --version
  else
    log "npm: not found"
  fi
}

ci_local() {
  local with_builder_e2e="false"
  local with_dev_check="false"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --with-builder-e2e)
        with_builder_e2e="true"
        shift
        ;;
      --with-dev-check)
        with_dev_check="true"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "unknown option for ci-local: $1"
        ;;
    esac
  done

  cd "${ROOT_DIR}"
  run_cmd ./scripts/archctl_validate.sh
  run_cmd ./.venv/bin/python -m pytest apps/orchestrator/tests
  (
    cd "${ROOT_DIR}/apps/builder"
    run_cmd npm run test:unit
  )
  if [[ "${with_builder_e2e}" == "true" ]]; then
    (
      cd "${ROOT_DIR}/apps/builder"
      run_cmd npm run test:e2e
    )
  fi
  if [[ "${with_dev_check}" == "true" ]]; then
    run_cmd ./scripts/dev_check.sh
  fi
  log "local CI checks passed"
}

deploy_azure() {
  require_gh

  local ref="main"
  local resource_group="rg-workcore-prod-uaen"
  local location="uaenorth"
  local deploy_frontdoor="true"
  local deploy_apim="true"
  local deploy_builder_ui="true"
  local swa_allow_insecure_tls_download="false"
  local configure_ui_entra_auth="false"
  local create_entra_app_registration="false"
  local entra_app_name="workcore-builder-swa"
  local enable_secondary_api_domain="false"
  local workcore_domain=""
  local api_primary_domain="api.hq21.tech"
  local api_secondary_domain="api.runwcr.com"
  local chatkit_domain=""
  local cors_allow_origins=""
  local integration_http_allowed_hosts=""
  local wait_for_completion="false"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --ref)
        ref="${2:-}"
        shift 2
        ;;
      --resource-group)
        resource_group="${2:-}"
        shift 2
        ;;
      --location)
        location="${2:-}"
        shift 2
        ;;
      --deploy-frontdoor)
        deploy_frontdoor="${2:-}"
        shift 2
        ;;
      --deploy-apim)
        deploy_apim="${2:-}"
        shift 2
        ;;
      --deploy-builder-ui)
        deploy_builder_ui="${2:-}"
        shift 2
        ;;
      --swa-allow-insecure-tls-download)
        swa_allow_insecure_tls_download="${2:-}"
        shift 2
        ;;
      --configure-ui-entra-auth)
        configure_ui_entra_auth="${2:-}"
        shift 2
        ;;
      --create-entra-app-registration)
        create_entra_app_registration="${2:-}"
        shift 2
        ;;
      --entra-app-name)
        entra_app_name="${2:-}"
        shift 2
        ;;
      --enable-secondary-api-domain)
        enable_secondary_api_domain="${2:-}"
        shift 2
        ;;
      --workcore-domain)
        workcore_domain="${2:-}"
        shift 2
        ;;
      --api-primary-domain)
        api_primary_domain="${2:-}"
        shift 2
        ;;
      --api-secondary-domain)
        api_secondary_domain="${2:-}"
        shift 2
        ;;
      --chatkit-domain)
        chatkit_domain="${2:-}"
        shift 2
        ;;
      --cors-allow-origins)
        cors_allow_origins="${2:-}"
        shift 2
        ;;
      --integration-http-allowed-hosts)
        integration_http_allowed_hosts="${2:-}"
        shift 2
        ;;
      --wait)
        wait_for_completion="true"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "unknown option for deploy-azure: $1"
        ;;
    esac
  done

  deploy_frontdoor="$(normalize_bool "${deploy_frontdoor}")"
  deploy_apim="$(normalize_bool "${deploy_apim}")"
  deploy_builder_ui="$(normalize_bool "${deploy_builder_ui}")"
  swa_allow_insecure_tls_download="$(normalize_bool "${swa_allow_insecure_tls_download}")"
  configure_ui_entra_auth="$(normalize_bool "${configure_ui_entra_auth}")"
  create_entra_app_registration="$(normalize_bool "${create_entra_app_registration}")"
  enable_secondary_api_domain="$(normalize_bool "${enable_secondary_api_domain}")"

  run_cmd gh workflow run "${WORKFLOW_DEPLOY}" \
    --ref "${ref}" \
    -f resource_group="${resource_group}" \
    -f location="${location}" \
    -f deploy_frontdoor="${deploy_frontdoor}" \
    -f deploy_apim="${deploy_apim}" \
    -f deploy_builder_ui="${deploy_builder_ui}" \
    -f swa_allow_insecure_tls_download="${swa_allow_insecure_tls_download}" \
    -f configure_ui_entra_auth="${configure_ui_entra_auth}" \
    -f create_entra_app_registration="${create_entra_app_registration}" \
    -f entra_app_name="${entra_app_name}" \
    -f enable_secondary_api_domain="${enable_secondary_api_domain}" \
    -f workcore_domain="${workcore_domain}" \
    -f api_primary_domain="${api_primary_domain}" \
    -f api_secondary_domain="${api_secondary_domain}" \
    -f chatkit_domain="${chatkit_domain}" \
    -f cors_allow_origins="${cors_allow_origins}" \
    -f integration_http_allowed_hosts="${integration_http_allowed_hosts}"

  log "deploy workflow dispatched"
  sleep 2
  local run_url
  run_url="$(gh run list --workflow "${WORKFLOW_DEPLOY}" --limit 1 --json url -q '.[0].url' || true)"
  if [[ -n "${run_url}" && "${run_url}" != "null" ]]; then
    log "latest run: ${run_url}"
  fi

  if [[ "${wait_for_completion}" == "true" ]]; then
    local run_id
    run_id="$(gh run list --workflow "${WORKFLOW_DEPLOY}" --limit 1 --json databaseId -q '.[0].databaseId')"
    [[ -n "${run_id}" && "${run_id}" != "null" ]] || fail "unable to resolve run id after dispatch"
    run_cmd gh run watch "${run_id}" --exit-status
  fi
}

list_runs() {
  require_gh
  local target="${1:-all}"
  if [[ $# -gt 0 ]]; then
    shift
  fi
  local limit="10"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit)
        limit="${2:-}"
        shift 2
        ;;
      *)
        fail "unknown option for runs: $1"
        ;;
    esac
  done

  case "${target}" in
    ci)
      run_cmd gh run list --workflow "${WORKFLOW_CI}" --limit "${limit}"
      ;;
    deploy)
      run_cmd gh run list --workflow "${WORKFLOW_DEPLOY}" --limit "${limit}"
      ;;
    all)
      run_cmd gh run list --limit "${limit}"
      ;;
    *)
      fail "unknown runs target: ${target} (use ci|deploy|all)"
      ;;
  esac
}

watch_run() {
  require_gh
  local run_id="${1:-}"
  [[ -n "${run_id}" ]] || fail "watch requires <run-id>"
  run_cmd gh run watch "${run_id}" --exit-status
}

view_run() {
  require_gh
  local run_id="${1:-}"
  [[ -n "${run_id}" ]] || fail "view requires <run-id>"
  shift || true
  local with_log="false"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --log)
        with_log="true"
        shift
        ;;
      *)
        fail "unknown option for view: $1"
        ;;
    esac
  done
  if [[ "${with_log}" == "true" ]]; then
    run_cmd gh run view "${run_id}" --log
  else
    run_cmd gh run view "${run_id}"
  fi
}

cancel_run() {
  require_gh
  local run_id="${1:-}"
  [[ -n "${run_id}" ]] || fail "cancel requires <run-id>"
  run_cmd gh run cancel "${run_id}"
}

main() {
  local command="${1:-help}"
  if [[ $# -gt 0 ]]; then
    shift
  fi
  case "${command}" in
    help|-h|--help)
      usage
      ;;
    doctor)
      doctor "$@"
      ;;
    ci-local)
      ci_local "$@"
      ;;
    deploy-azure)
      deploy_azure "$@"
      ;;
    runs)
      list_runs "$@"
      ;;
    watch)
      watch_run "$@"
      ;;
    view)
      view_run "$@"
      ;;
    cancel)
      cancel_run "$@"
      ;;
    *)
      fail "unknown command: ${command}"
      ;;
  esac
}

main "$@"
