#!/usr/bin/env python3
"""Fail fast when public chat contract docs/runtime drift out of sync."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
    print(
        "PyYAML is required for check_public_contract_drift.py. Install with `pip install pyyaml`.",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


ROOT = Path(__file__).resolve().parent.parent
SUNSET_HTTP_DATE = "Sat, 04 Apr 2026 00:00:00 GMT"
SUNSET_ISO_TIMESTAMP = "2026-04-04T00:00:00Z"


def _read_text(path: Path, errors: list[str]) -> str:
    if not path.exists():
        errors.append(f"missing required file: {path}")
        return ""
    return path.read_text(encoding="utf-8")


def _has_headers(response: dict[str, Any], required: tuple[str, ...]) -> bool:
    headers = response.get("headers")
    if not isinstance(headers, dict):
        return False
    return all(name in headers for name in required)


def main() -> int:
    errors: list[str] = []

    openapi_path = ROOT / "docs" / "api" / "openapi.yaml"
    openapi_text = _read_text(openapi_path, errors)
    openapi_data: dict[str, Any] = {}
    if openapi_text:
        try:
            loaded = yaml.safe_load(openapi_text)
            if isinstance(loaded, dict):
                openapi_data = loaded
            else:
                errors.append("docs/api/openapi.yaml root must be a mapping")
        except yaml.YAMLError as exc:
            errors.append(f"failed to parse docs/api/openapi.yaml: {exc}")

    paths = openapi_data.get("paths", {}) if isinstance(openapi_data, dict) else {}
    if not isinstance(paths, dict):
        errors.append("OpenAPI `paths` must be a mapping")
        paths = {}

    chat_post = (paths.get("/chat") or {}).get("post")
    if not isinstance(chat_post, dict):
        errors.append("OpenAPI must define canonical `POST /chat`")

    chatkit_post = (paths.get("/chatkit") or {}).get("post")
    if not isinstance(chatkit_post, dict):
        errors.append("OpenAPI must define compatibility alias `POST /chatkit`")
    else:
        if chatkit_post.get("deprecated") is not True:
            errors.append("OpenAPI `POST /chatkit` must be marked `deprecated: true`")
        description = str(chatkit_post.get("description", ""))
        if "410 Gone" not in description:
            errors.append("OpenAPI `POST /chatkit` description must document `410 Gone` sunset behavior")
        if SUNSET_HTTP_DATE not in description:
            errors.append("OpenAPI `POST /chatkit` description must include the fixed Sunset HTTP-date")

        responses = chatkit_post.get("responses", {})
        if not isinstance(responses, dict):
            errors.append("OpenAPI `POST /chatkit` responses must be a mapping")
        else:
            response_200 = responses.get("200")
            response_410 = responses.get("410")
            if not isinstance(response_200, dict):
                errors.append("OpenAPI `POST /chatkit` must expose `200` response during transition window")
            elif not _has_headers(response_200, ("Deprecation", "Sunset")):
                errors.append("OpenAPI `POST /chatkit` `200` response must expose Deprecation + Sunset headers")

            if not isinstance(response_410, dict):
                errors.append("OpenAPI `POST /chatkit` must expose `410` response after sunset")
            elif not _has_headers(response_410, ("Deprecation", "Sunset")):
                errors.append("OpenAPI `POST /chatkit` `410` response must expose Deprecation + Sunset headers")

    headers = ((openapi_data.get("components") or {}).get("headers") or {}) if isinstance(openapi_data, dict) else {}
    if not isinstance(headers, dict) or "Deprecation" not in headers or "Sunset" not in headers:
        errors.append("OpenAPI components.headers must define both `Deprecation` and `Sunset`")

    schemas = ((openapi_data.get("components") or {}).get("schemas") or {}) if isinstance(openapi_data, dict) else {}
    if not isinstance(schemas, dict):
        errors.append("OpenAPI components.schemas must be a mapping")
        schemas = {}

    integration_manifest_schema = schemas.get("IntegrationManifest")
    if not isinstance(integration_manifest_schema, dict):
        errors.append("OpenAPI must define components.schemas.IntegrationManifest")
    else:
        manifest_props = integration_manifest_schema.get("properties", {})
        if not isinstance(manifest_props, dict):
            errors.append("IntegrationManifest.properties must be a mapping")
        else:
            required_manifest_props = (
                "api_base_url",
                "chat_api_url",
                "deprecated_chat_alias_url",
                "auth_profile",
                "required_headers",
                "optional_headers",
                "project_scope",
                "deprecations",
                "secret_expiry",
            )
            for key in required_manifest_props:
                if key not in manifest_props:
                    errors.append(f"IntegrationManifest must define `{key}`")

    kit_schema = schemas.get("AgentIntegrationKit")
    if not isinstance(kit_schema, dict):
        errors.append("OpenAPI must define components.schemas.AgentIntegrationKit")
    else:
        kit_props = kit_schema.get("properties", {})
        if not isinstance(kit_props, dict) or "integration_manifest" not in kit_props:
            errors.append("AgentIntegrationKit must expose `integration_manifest`")

    report_schema = schemas.get("AgentIntegrationCheckReport")
    if not isinstance(report_schema, dict):
        errors.append("OpenAPI must define components.schemas.AgentIntegrationCheckReport")
    else:
        report_props = report_schema.get("properties", {})
        if not isinstance(report_props, dict):
            errors.append("AgentIntegrationCheckReport.properties must be a mapping")
        else:
            if "integration_manifest" not in report_props:
                errors.append("AgentIntegrationCheckReport must expose `integration_manifest`")
            summary = report_props.get("summary")
            if isinstance(summary, dict):
                summary_props = summary.get("properties", {})
                if isinstance(summary_props, dict):
                    warned = summary_props.get("warned")
                    if not isinstance(warned, dict):
                        errors.append("AgentIntegrationCheckReport.summary must include `warned` counter")
            else:
                errors.append("AgentIntegrationCheckReport.summary must be defined")

    check_schema = schemas.get("AgentIntegrationCheckItem")
    if not isinstance(check_schema, dict):
        errors.append("OpenAPI must define components.schemas.AgentIntegrationCheckItem")
    else:
        check_props = check_schema.get("properties", {})
        if not isinstance(check_props, dict):
            errors.append("AgentIntegrationCheckItem.properties must be a mapping")
        else:
            for key in (
                "status",
                "severity",
                "code",
                "title",
                "message",
                "observed",
                "expected",
                "remediation",
                "docs_ref",
            ):
                if key not in check_props:
                    errors.append(f"AgentIntegrationCheckItem must define `{key}`")
            status_schema = check_props.get("status")
            if isinstance(status_schema, dict):
                enum_values = status_schema.get("enum", [])
                if not isinstance(enum_values, list) or set(enum_values) != {"PASS", "WARN", "FAIL"}:
                    errors.append("AgentIntegrationCheckItem.status enum must be exactly PASS/WARN/FAIL")
            else:
                errors.append("AgentIntegrationCheckItem.status must be an enum")

    if "/chat" not in openapi_text:
        errors.append("OpenAPI must document canonical `/chat` references for onboarding surfaces")
    if "chat_api_url" not in openapi_text:
        errors.append("OpenAPI must include `chat_api_url` in onboarding manifest contract")

    reference_text = _read_text(ROOT / "docs" / "api" / "reference.md", errors)
    for required_snippet in (
        "POST /chat",
        "POST /chatkit",
        "Deprecation: true",
        SUNSET_HTTP_DATE,
        "410 Gone",
    ):
        if required_snippet not in reference_text:
            errors.append(f"docs/api/reference.md missing required chat lifecycle snippet: `{required_snippet}`")
    if "integration_manifest" not in reference_text:
        errors.append("docs/api/reference.md must document `integration_manifest`")
    if "status` (`PASS` | `WARN` | `FAIL`)" not in reference_text:
        errors.append("docs/api/reference.md must document doctor check PASS/WARN/FAIL statuses")

    guide_text = _read_text(ROOT / "docs" / "integration" / "workcore-api-integration-guide.md", errors)
    for required_snippet in (
        "POST /chat",
        "POST /chatkit",
        "410 Gone",
    ):
        if required_snippet not in guide_text:
            errors.append(
                "docs/integration/workcore-api-integration-guide.md missing required chat lifecycle snippet: "
                f"`{required_snippet}`"
            )
    if "integration_manifest" not in guide_text:
        errors.append("Integration guide must document `integration_manifest`")
    if "Canonical onboarding manifest expectations" not in guide_text:
        errors.append("Integration guide must document canonical onboarding manifest expectations")

    cutover_text = _read_text(ROOT / "docs" / "integration" / "chat-cutover-notice-2026-03-04.md", errors)
    for required_snippet in (
        "POST /chat",
        "POST /chatkit",
        SUNSET_HTTP_DATE,
        "https://api.runwcr.com",
        "https://api.hq21.tech",
    ):
        if required_snippet not in cutover_text:
            errors.append(
                "docs/integration/chat-cutover-notice-2026-03-04.md missing required cutover snippet: "
                f"`{required_snippet}`"
            )
    if re.search(r"https?://chatkit\.", cutover_text):
        errors.append("Cutover notice must not advertise `chatkit.*` hostnames as public API hosts")

    def _ensure_chatkit_mentions_are_deprecated(label: str, text: str) -> None:
        if "/chatkit" not in text:
            return
        lowered = text.lower()
        if "deprecated" not in lowered and "compatibility alias" not in lowered:
            errors.append(f"{label} references `/chatkit` without deprecation context")
        if SUNSET_HTTP_DATE not in text and SUNSET_ISO_TIMESTAMP not in text:
            errors.append(f"{label} references `/chatkit` without explicit sunset marker")

    _ensure_chatkit_mentions_are_deprecated("docs/api/reference.md", reference_text)
    _ensure_chatkit_mentions_are_deprecated("docs/integration/workcore-api-integration-guide.md", guide_text)
    _ensure_chatkit_mentions_are_deprecated(
        "docs/integration/chat-cutover-notice-2026-03-04.md",
        cutover_text,
    )

    runtime_targets = (
        ROOT / "apps" / "orchestrator" / "chatkit" / "app.py",
        ROOT / "apps" / "orchestrator" / "chatkit" / "service.py",
    )
    for runtime_path in runtime_targets:
        runtime_text = _read_text(runtime_path, errors)
        for required_snippet in (
            '_CHAT_ENDPOINT_PATH = "/chat"',
            '_CHATKIT_ALIAS_PATH = "/chatkit"',
            'response.headers["Deprecation"]',
            'response.headers["Sunset"]',
            "status_code=410",
        ):
            if required_snippet not in runtime_text:
                errors.append(f"{runtime_path} missing runtime alias policy snippet: `{required_snippet}`")

    integration_kit_text = _read_text(ROOT / "apps" / "orchestrator" / "api" / "app.py", errors)
    for required_snippet in (
        "openapi_chatkit_alias_policy",
        "integration_manifest_chat_canonical",
        "deprecated_chatkit_partner_reference",
        "secret_expiry_warning_level_present",
        "/chat",
        "/chatkit",
        "Deprecation",
        "Sunset",
        "'410':",
    ):
        if required_snippet not in integration_kit_text:
            errors.append(
                "apps/orchestrator/api/app.py missing integration check snippet for chat alias policy: "
                f"`{required_snippet}`"
            )

    onboarding_text = _read_text(ROOT / "apps" / "orchestrator" / "api" / "partner_self_service.py", errors)
    for required_snippet in (
        'chat_api_url = f"{normalized_base_url}{_CHAT_API_PATH}"',
        '"deprecated_chat_alias_url"',
        '"integration_manifest.json"',
        '"curl_examples/check_auth.sh"',
        '"curl_examples/check_project_scope.sh"',
        '"curl_examples/check_chat.sh"',
        "sunset at 2026-04-04T00:00:00Z",
    ):
        if required_snippet not in onboarding_text:
            errors.append(
                "partner onboarding package generator missing expected canonical onboarding snippet: "
                f"`{required_snippet}`"
            )
    _ensure_chatkit_mentions_are_deprecated("apps/orchestrator/api/partner_self_service.py", onboarding_text)

    if SUNSET_ISO_TIMESTAMP not in onboarding_text and SUNSET_ISO_TIMESTAMP not in reference_text:
        errors.append("Sunset timestamp must remain visible in partner-facing onboarding content")

    if errors:
        print("Public chat contract drift detected:", file=sys.stderr)
        for issue in errors:
            print(f"- {issue}", file=sys.stderr)
        return 1

    print("Public chat contract drift check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
