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

    integration_capabilities_get = (paths.get("/integration-capabilities") or {}).get("get")
    if not isinstance(integration_capabilities_get, dict):
        errors.append("OpenAPI must define `GET /integration-capabilities`")
    else:
        if integration_capabilities_get.get("security") != []:
            errors.append("OpenAPI `GET /integration-capabilities` must be public with `security: []`")
        negotiation_text = " ".join(
            [
                str(integration_capabilities_get.get("summary") or ""),
                str(integration_capabilities_get.get("description") or ""),
            ]
        ).lower()
        if "negotiation" not in negotiation_text:
            errors.append("OpenAPI `GET /integration-capabilities` must describe feature negotiation purpose")

    for path_name in ("/capabilities", "/capabilities/{capability_id}/versions"):
        path_item = paths.get(path_name)
        if not isinstance(path_item, dict):
            errors.append(f"OpenAPI must define `{path_name}` as capability registry surface")
            continue
        for method_name in ("get", "post"):
            operation = path_item.get(method_name)
            if not isinstance(operation, dict):
                continue
            operation_text = " ".join(
                [
                    str(operation.get("summary") or ""),
                    str(operation.get("description") or ""),
                ]
            ).lower()
            if "negotiation" in operation_text and "not client feature negotiation" not in operation_text:
                errors.append(
                    f"OpenAPI `{method_name.upper()} {path_name}` must remain registry-oriented, "
                    "not a negotiation endpoint"
                )

    headers = ((openapi_data.get("components") or {}).get("headers") or {}) if isinstance(openapi_data, dict) else {}
    if not isinstance(headers, dict) or "Deprecation" not in headers or "Sunset" not in headers:
        errors.append("OpenAPI components.headers must define both `Deprecation` and `Sunset`")

    schemas = ((openapi_data.get("components") or {}).get("schemas") or {}) if isinstance(openapi_data, dict) else {}
    if not isinstance(schemas, dict):
        errors.append("OpenAPI components.schemas must be a mapping")
        schemas = {}

    platform_error_schema = schemas.get("PlatformError")
    if not isinstance(platform_error_schema, dict):
        errors.append("OpenAPI must define components.schemas.PlatformError")
    else:
        platform_error_props = platform_error_schema.get("properties", {})
        if not isinstance(platform_error_props, dict):
            errors.append("PlatformError.properties must be a mapping")
        else:
            for key in (
                "code",
                "message",
                "category",
                "retryable",
                "retry_after_s",
                "bad_fields",
                "unsupported_feature",
                "docs_ref",
                "details",
                "correlation_id",
            ):
                if key not in platform_error_props:
                    errors.append(f"PlatformError must define `{key}`")
            category_schema = platform_error_props.get("category")
            if isinstance(category_schema, dict):
                category_enum = category_schema.get("enum", [])
                expected_categories = {
                    "auth",
                    "validation",
                    "configuration",
                    "not_found",
                    "conflict",
                    "unsupported_feature",
                    "transient",
                    "internal",
                    "route",
                    "action",
                }
                if not isinstance(category_enum, list) or not expected_categories.issubset(set(category_enum)):
                    errors.append("PlatformError.category enum must include the full typed taxonomy")
            else:
                errors.append("PlatformError.category must be defined as an enum")

    platform_error_envelope_schema = schemas.get("PlatformErrorEnvelope")
    if not isinstance(platform_error_envelope_schema, dict):
        errors.append("OpenAPI must define components.schemas.PlatformErrorEnvelope")
    else:
        envelope_props = platform_error_envelope_schema.get("properties", {})
        if not isinstance(envelope_props, dict):
            errors.append("PlatformErrorEnvelope.properties must be a mapping")
        else:
            error_prop = envelope_props.get("error")
            if not isinstance(error_prop, dict) or error_prop.get("$ref") != "#/components/schemas/PlatformError":
                errors.append("PlatformErrorEnvelope.error must reference PlatformError")

    error_envelope_schema = schemas.get("ErrorEnvelope")
    if not isinstance(error_envelope_schema, dict):
        errors.append("OpenAPI must define components.schemas.ErrorEnvelope")
    else:
        all_of = error_envelope_schema.get("allOf", [])
        if not isinstance(all_of, list) or not any(
            isinstance(item, dict) and item.get("$ref") == "#/components/schemas/PlatformErrorEnvelope"
            for item in all_of
        ):
            errors.append("ErrorEnvelope must remain a compatibility alias over PlatformErrorEnvelope")

    orchestrator_action_error_schema = schemas.get("OrchestratorActionError")
    if not isinstance(orchestrator_action_error_schema, dict):
        errors.append("OpenAPI must define components.schemas.OrchestratorActionError")
    else:
        all_of = orchestrator_action_error_schema.get("allOf", [])
        if not isinstance(all_of, list):
            errors.append("OrchestratorActionError.allOf must be a list")
        else:
            has_platform_ref = any(
                isinstance(item, dict) and item.get("$ref") == "#/components/schemas/PlatformError"
                for item in all_of
            )
            has_required_action = any(
                isinstance(item, dict)
                and isinstance(item.get("properties"), dict)
                and "action" in item.get("properties", {})
                and isinstance(item.get("required"), list)
                and "action" in item.get("required", [])
                for item in all_of
            )
            if not has_platform_ref or not has_required_action:
                errors.append("OrchestratorActionError must align as PlatformError + required action")

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
                "integration_capabilities_url",
                "host_policy",
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
            manifest_required = integration_manifest_schema.get("required", [])
            if not isinstance(manifest_required, list) or "integration_capabilities_url" not in manifest_required:
                errors.append("IntegrationManifest.required must include `integration_capabilities_url`")

    kit_schema = schemas.get("AgentIntegrationKit")
    if not isinstance(kit_schema, dict):
        errors.append("OpenAPI must define components.schemas.AgentIntegrationKit")
    else:
        kit_props = kit_schema.get("properties", {})
        if not isinstance(kit_props, dict) or "integration_manifest" not in kit_props:
            errors.append("AgentIntegrationKit must expose `integration_manifest`")
        urls_schema = kit_props.get("urls")
        if isinstance(urls_schema, dict):
            urls_props = urls_schema.get("properties", {})
            if not isinstance(urls_props, dict) or "integration_capabilities" not in urls_props:
                errors.append("AgentIntegrationKit.urls must include `integration_capabilities`")
        else:
            errors.append("AgentIntegrationKit.urls must be defined")

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
            report_urls_schema = report_props.get("urls")
            if isinstance(report_urls_schema, dict):
                report_urls_props = report_urls_schema.get("properties", {})
                if not isinstance(report_urls_props, dict) or "integration_capabilities" not in report_urls_props:
                    errors.append("AgentIntegrationCheckReport.urls must include `integration_capabilities`")
            else:
                errors.append("AgentIntegrationCheckReport.urls must be defined")
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
    if "host_policy" not in openapi_text:
        errors.append("OpenAPI must include `host_policy` in onboarding manifest contract")

    reference_text = _read_text(ROOT / "docs" / "api" / "reference.md", errors)
    for required_snippet in (
        "POST /chat",
        "POST /chatkit",
        "GET /integration-capabilities",
        "Deprecation: true",
        SUNSET_HTTP_DATE,
        "410 Gone",
    ):
        if required_snippet not in reference_text:
            errors.append(f"docs/api/reference.md missing required chat lifecycle snippet: `{required_snippet}`")
    if "integration_manifest" not in reference_text:
        errors.append("docs/api/reference.md must document `integration_manifest`")
    if "integration_capabilities_url" not in reference_text:
        errors.append("docs/api/reference.md must document `integration_capabilities_url`")
    if "/capabilities*" not in reference_text:
        errors.append("docs/api/reference.md must keep capability registry/negotiation separation guidance")
    if "status` (`PASS` | `WARN` | `FAIL`)" not in reference_text:
        errors.append("docs/api/reference.md must document doctor check PASS/WARN/FAIL statuses")

    guide_text = _read_text(ROOT / "docs" / "integration" / "workcore-api-integration-guide.md", errors)
    for required_snippet in (
        "POST /chat",
        "POST /chatkit",
        "GET /integration-capabilities",
        "integration_capabilities_url",
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
    if "/capabilities*" not in guide_text:
        errors.append("Integration guide must keep capability registry/negotiation separation guidance")
    guide_lower = guide_text.lower()
    if "primary host" in guide_lower or "alias host" in guide_lower:
        errors.append("Integration guide must not describe onboarding host model via primary/alias language")

    runtime_arch_text = _read_text(ROOT / "docs" / "architecture" / "runtime.md", errors)
    for required_snippet in (
        "PlatformErrorEnvelope",
        "GET /integration-capabilities",
        "/capabilities*",
    ):
        if required_snippet not in runtime_arch_text:
            errors.append(
                "docs/architecture/runtime.md missing required typed error/negotiation snippet: "
                f"`{required_snippet}`"
            )

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
        "integration_capabilities_contract_url_present",
        "host_policy_compliance",
        "deprecated_chatkit_partner_reference",
        "secret_expiry_warning_level_present",
        "/integration-capabilities",
        "integration_capabilities_url",
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
        "resolve_partner_host_policy",
        "_PARTNER_HOST_POLICY_BY_PARTNER_ID",
        "pinned_runwcr",
        'chat_api_url = f"{normalized_base_url}{_CHAT_API_PATH}"',
        'integration_capabilities_url = f"{normalized_base_url}{_INTEGRATION_CAPABILITIES_PATH}"',
        '"deprecated_chat_alias_url"',
        '"integration_capabilities_url"',
        '"host_policy":',
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
    if "_EPAM_MARKER" in onboarding_text or "contains(\"epam\")" in onboarding_text:
        errors.append("partner onboarding host logic must use explicit host policy mapping, not epam marker heuristics")
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
