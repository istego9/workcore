#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

check_api_changelog_guard() {
  local git_bin
  git_bin="$(command -v git || true)"
  if [[ -z "${git_bin}" ]]; then
    return 0
  fi

  if ! "${git_bin}" -C "${ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 0
  fi

  local api_status
  api_status="$("${git_bin}" -C "${ROOT}" status --porcelain -- docs/api/openapi.yaml docs/api/schemas 2>/dev/null || true)"
  if [[ -z "${api_status}" ]]; then
    return 0
  fi

  local changelog_status
  changelog_status="$("${git_bin}" -C "${ROOT}" status --porcelain -- CHANGELOG.md 2>/dev/null || true)"
  if [[ -z "${changelog_status}" ]]; then
    echo "API contract changes detected, but CHANGELOG.md was not updated." >&2
    echo "Update CHANGELOG.md in the same change-set when editing docs/api/openapi.yaml or docs/api/schemas/*.json." >&2
    return 1
  fi

  local py
  py="python3"
  if [[ -x "${ROOT}/.venv/bin/python" ]]; then
    py="${ROOT}/.venv/bin/python"
  fi

  WORKCORE_ROOT="${ROOT}" "${py}" - <<'PY'
import os
import re
import sys
from pathlib import Path

root = Path(os.environ["WORKCORE_ROOT"]).resolve()
openapi_path = root / "docs" / "api" / "openapi.yaml"
changelog_path = root / "CHANGELOG.md"

openapi_text = openapi_path.read_text(encoding="utf-8")
version_match = re.search(r"(?m)^\s*version:\s*([^\s]+)\s*$", openapi_text)
if not version_match:
    print("Unable to find OpenAPI version in docs/api/openapi.yaml", file=sys.stderr)
    sys.exit(1)
openapi_version = version_match.group(1).strip()

changelog_text = changelog_path.read_text(encoding="utf-8")
entry_match = re.search(r"(?ms)^##\s+.+?(?=^##\s+|\Z)", changelog_text)
if not entry_match:
    print("CHANGELOG.md must contain at least one dated entry starting with '## '", file=sys.stderr)
    sys.exit(1)
entry = entry_match.group(0)

if "### API diff vs previous version" not in entry:
    print(
        "Latest CHANGELOG entry must include '### API diff vs previous version' for API changes.",
        file=sys.stderr,
    )
    sys.exit(1)

prev_match = re.search(r"(?m)^-\s+Previous API version:\s+`([^`]+)`\s*$", entry)
curr_match = re.search(r"(?m)^-\s+Current API version:\s+`([^`]+)`\s*$", entry)
if not prev_match or not curr_match:
    print(
        "Latest CHANGELOG entry must include '- Previous API version: `...`' and '- Current API version: `...`'.",
        file=sys.stderr,
    )
    sys.exit(1)

curr_version = curr_match.group(1).strip()
if curr_version != openapi_version:
    print(
        f"CHANGELOG current API version '{curr_version}' must match OpenAPI version '{openapi_version}'.",
        file=sys.stderr,
    )
    sys.exit(1)

if not re.search(r"(?m)^###\s+(Added|Changed|Deprecated|Removed)\s*$", entry):
    print(
        "Latest CHANGELOG entry must include at least one of sections: Added/Changed/Deprecated/Removed.",
        file=sys.stderr,
    )
    sys.exit(1)
PY
}

if command -v archctl >/dev/null 2>&1; then
  archctl validate
  check_api_changelog_guard
  exit 0
fi

echo "archctl is not available; running repository fallback validation"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT}/.venv/bin/python"
fi

WORKCORE_ROOT="${ROOT}" "${PYTHON_BIN}" - <<'PY'
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["WORKCORE_ROOT"]).resolve()

openapi_path = root / "docs" / "api" / "openapi.yaml"
schema_dir = root / "docs" / "api" / "schemas"
migrations_dir = root / "db" / "migrations"

if not openapi_path.exists():
    print(f"missing required file: {openapi_path}", file=sys.stderr)
    sys.exit(1)

if not schema_dir.exists():
    print(f"missing required directory: {schema_dir}", file=sys.stderr)
    sys.exit(1)

if not migrations_dir.exists():
    print(f"missing required directory: {migrations_dir}", file=sys.stderr)
    sys.exit(1)

try:
    import yaml
except ModuleNotFoundError as exc:
    print(
        "PyYAML is required for fallback validation when archctl is unavailable. "
        "Install it with `pip install pyyaml` or install archctl.",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

with open(openapi_path, "r", encoding="utf-8") as f:
    yaml.safe_load(f)

for path in sorted(schema_dir.glob("*.json")):
    with open(path, "r", encoding="utf-8") as f:
        json.load(f)

migration_files = sorted(migrations_dir.glob("*.sql"))
if not migration_files:
    print("no SQL migrations found under db/migrations", file=sys.stderr)
    sys.exit(1)

names = [p.name for p in migration_files]
if names != sorted(names):
    print("migration filenames are not sorted lexicographically", file=sys.stderr)
    sys.exit(1)

if len(names) != len(set(names)):
    print("duplicate migration filenames detected", file=sys.stderr)
    sys.exit(1)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        print(f"missing required env file: {path}", file=sys.stderr)
        sys.exit(1)
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


docker_env_example = parse_env_file(root / ".env.docker.example")

for required in (
    "WORKCORE_API_AUTH_TOKEN",
    "WEBHOOK_DEFAULT_INBOUND_SECRET",
    "CORS_ALLOW_ORIGINS",
    "INTEGRATION_HTTP_ALLOWED_HOSTS",
):
    if not docker_env_example.get(required):
        print(f".env.docker.example must set non-empty {required}", file=sys.stderr)
        sys.exit(1)

if docker_env_example.get("WORKCORE_HTTP_PORT") != "8080":
    print(".env.docker.example must set WORKCORE_HTTP_PORT=8080", file=sys.stderr)
    sys.exit(1)

if docker_env_example.get("WORKCORE_HTTPS_PORT") != "8443":
    print(".env.docker.example must set WORKCORE_HTTPS_PORT=8443", file=sys.stderr)
    sys.exit(1)

cors_allow_origins = docker_env_example.get("CORS_ALLOW_ORIGINS", "")
if "*" in cors_allow_origins:
    print(".env.docker.example CORS_ALLOW_ORIGINS must not contain '*'", file=sys.stderr)
    sys.exit(1)

print("fallback validation passed")
PY

check_api_changelog_guard
