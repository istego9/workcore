from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

_ROOT_DIR = Path(__file__).resolve().parents[3]
_ONBOARD_SCRIPT_PATH = _ROOT_DIR / "deploy" / "azure" / "scripts" / "apim_partner_onboard.sh"
_PORTAL_TEMPLATE_PATH = _ROOT_DIR / "docs" / "integration" / "partner-self-service-portal.html"
_PARTNER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_DEFAULT_HOST_POLICY_ID = "public_request_host"
_PINNED_RUNWCR_POLICY_ID = "pinned_runwcr"
_PINNED_RUNWCR_BASE_URL = "https://api.runwcr.com"
_PINNED_RUNWCR_ALLOWED_DOMAINS = ["api.runwcr.com"]
_HOST_POLICY_MODES = {"request_host", "pinned"}
_HOST_POLICY_ENFORCEMENTS = {"advisory", "required"}
_HOST_POLICY_CATALOG: dict[str, dict[str, Any]] = {
    _DEFAULT_HOST_POLICY_ID: {
        "policy_id": _DEFAULT_HOST_POLICY_ID,
        "mode": "request_host",
        "enforcement": "advisory",
        "canonical_base_url": "",
        "allowed_domains": [],
        "notes": [
            "Use caller-visible public API host.",
            "Canonical chat endpoint remains POST /chat.",
        ],
    },
    _PINNED_RUNWCR_POLICY_ID: {
        "policy_id": _PINNED_RUNWCR_POLICY_ID,
        "mode": "pinned",
        "enforcement": "required",
        "canonical_base_url": _PINNED_RUNWCR_BASE_URL,
        "allowed_domains": list(_PINNED_RUNWCR_ALLOWED_DOMAINS),
        "notes": [
            "Partner host policy is pinned to https://api.runwcr.com.",
            "Only api.runwcr.com is allowed in generated onboarding artifacts.",
        ],
    },
}
_PARTNER_HOST_POLICY_BY_PARTNER_ID: dict[str, str] = {
    "epam_future-insurance": _PINNED_RUNWCR_POLICY_ID,
}
_CHAT_API_PATH = "/chat"
_CHATKIT_ALIAS_PATH = "/chatkit"
_INTEGRATION_CAPABILITIES_PATH = "/integration-capabilities"
_CHATKIT_ALIAS_SUNSET_AT = datetime(2026, 4, 4, 0, 0, 0, tzinfo=timezone.utc)
_DEFAULT_SCOPE = "api://workcore-partner-api/.default"
_DEFAULT_TOKEN_ENDPOINT_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_SECRET_ROTATION_BUFFER_DAYS = 30


class PartnerSelfServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int, details: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


@dataclass(frozen=True)
class PartnerPortalIdentity:
    tenant_id: str
    user_id: str
    user_email: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _base_url_without_trailing_slash(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    return normalized or "https://api.hq21.tech"


def _host_from_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return (parsed.hostname or "").strip().lower()


def _normalize_partner_id(value: str | None) -> str:
    return (value or "").strip().lower()


def _policy_template(policy_id: str) -> dict[str, Any]:
    template = _HOST_POLICY_CATALOG.get(policy_id)
    if not isinstance(template, dict):
        raise PartnerSelfServiceError("INVALID_ARGUMENT", f"unknown host_policy `{policy_id}`", 422)
    return {
        "policy_id": str(template.get("policy_id") or policy_id),
        "mode": str(template.get("mode") or "request_host"),
        "enforcement": str(template.get("enforcement") or "advisory"),
        "canonical_base_url": str(template.get("canonical_base_url") or ""),
        "allowed_domains": [str(item).strip().lower() for item in template.get("allowed_domains", []) if str(item).strip()],
        "notes": [str(item).strip() for item in template.get("notes", []) if str(item).strip()],
    }


def resolve_partner_host_policy(
    *,
    partner_id: str | None = None,
    requested_policy_id: str | None = None,
) -> dict[str, Any]:
    normalized_partner_id = _normalize_partner_id(partner_id)
    requested = (requested_policy_id or "").strip()
    if requested and requested not in _HOST_POLICY_CATALOG:
        raise PartnerSelfServiceError("INVALID_ARGUMENT", f"host_policy must be one of {sorted(_HOST_POLICY_CATALOG)}", 422)

    enforced_policy_id = _PARTNER_HOST_POLICY_BY_PARTNER_ID.get(normalized_partner_id)
    resolved_policy_id = enforced_policy_id or requested or _DEFAULT_HOST_POLICY_ID
    policy = _policy_template(resolved_policy_id)
    if normalized_partner_id:
        policy["partner_id"] = normalized_partner_id
    if enforced_policy_id and requested and requested != enforced_policy_id:
        notes = list(policy.get("notes", []))
        notes.append(f"Requested host_policy `{requested}` overridden by enforced partner policy.")
        policy["notes"] = notes
    return policy


def _normalize_manifest_host_policy(
    *,
    host_policy: Mapping[str, Any] | None,
    normalized_base_url: str,
    resolved_allowed_domains: list[str],
    partner_id: str | None,
) -> dict[str, Any]:
    mode = "request_host"
    enforcement = "advisory"
    policy_id = _DEFAULT_HOST_POLICY_ID
    canonical_base_url = normalized_base_url
    notes: list[str] = []
    host_policy_allowed_domains: list[str] = list(resolved_allowed_domains)
    policy_partner_id = _normalize_partner_id(partner_id) or None

    if isinstance(host_policy, Mapping):
        candidate_mode = str(host_policy.get("mode") or "").strip().lower()
        if candidate_mode in _HOST_POLICY_MODES:
            mode = candidate_mode
        candidate_enforcement = str(host_policy.get("enforcement") or "").strip().lower()
        if candidate_enforcement in _HOST_POLICY_ENFORCEMENTS:
            enforcement = candidate_enforcement
        candidate_policy_id = str(host_policy.get("policy_id") or "").strip()
        if candidate_policy_id:
            policy_id = candidate_policy_id
        candidate_canonical_base_url = _base_url_without_trailing_slash(str(host_policy.get("canonical_base_url") or ""))
        if candidate_canonical_base_url:
            canonical_base_url = candidate_canonical_base_url
        candidate_allowed_domains = [
            str(item).strip().lower()
            for item in host_policy.get("allowed_domains", [])
            if str(item).strip()
        ]
        if candidate_allowed_domains:
            host_policy_allowed_domains = candidate_allowed_domains
        notes = [str(item).strip() for item in host_policy.get("notes", []) if str(item).strip()]
        candidate_partner_id = _normalize_partner_id(str(host_policy.get("partner_id") or ""))
        if candidate_partner_id:
            policy_partner_id = candidate_partner_id

    if mode == "pinned":
        canonical_base_url = _base_url_without_trailing_slash(canonical_base_url or normalized_base_url)
        if not host_policy_allowed_domains:
            pinned_host = _host_from_base_url(canonical_base_url)
            host_policy_allowed_domains = [pinned_host] if pinned_host else []

    if not host_policy_allowed_domains:
        default_host = _host_from_base_url(normalized_base_url)
        host_policy_allowed_domains = [default_host] if default_host else []

    return {
        "policy_id": policy_id,
        "mode": mode,
        "enforcement": enforcement,
        "canonical_base_url": canonical_base_url,
        "allowed_domains": host_policy_allowed_domains,
        "partner_id": policy_partner_id,
        "notes": notes,
    }


def apply_host_policy_to_target(
    *,
    base_url: str,
    allowed_domains: list[str],
    host_policy: Mapping[str, Any] | None,
) -> tuple[str, list[str]]:
    if not isinstance(host_policy, Mapping):
        return base_url, allowed_domains
    mode = str(host_policy.get("mode") or "").strip().lower()
    if mode != "pinned":
        return base_url, allowed_domains

    canonical_base_url = _base_url_without_trailing_slash(str(host_policy.get("canonical_base_url") or ""))
    if not canonical_base_url:
        raise PartnerSelfServiceError("INTERNAL", "pinned host policy requires canonical_base_url", 500)
    pinned_domains = [
        str(item).strip().lower()
        for item in host_policy.get("allowed_domains", [])
        if str(item).strip()
    ]
    if not pinned_domains:
        host = _host_from_base_url(canonical_base_url)
        if host:
            pinned_domains = [host]
    return canonical_base_url, pinned_domains


def public_host_policy_catalog() -> dict[str, dict[str, Any]]:
    return {policy_id: _policy_template(policy_id) for policy_id in _HOST_POLICY_CATALOG}


def public_partner_host_policy_bindings() -> dict[str, str]:
    return dict(_PARTNER_HOST_POLICY_BY_PARTNER_ID)


def _token_endpoint_for_manifest(explicit_endpoint: str | None, tenant_id: str | None) -> str:
    endpoint = (explicit_endpoint or "").strip()
    if endpoint:
        return endpoint
    tenant = (tenant_id or "").strip() or "<tenant_id>"
    return _DEFAULT_TOKEN_ENDPOINT_TEMPLATE.format(tenant_id=tenant)


def _secret_expiry_payload(
    *,
    now: datetime,
    validity_policy: str,
    issued_at: datetime | None,
    expires_at: datetime | None,
) -> dict[str, Any]:
    warning_level = "unknown"
    warning_message = "Secret expiry is unknown. Generate onboarding package to get exact expiry."
    rotation_due_at: datetime | None = None

    if expires_at is not None:
        days_left = (expires_at - now).total_seconds() / 86400
        rotation_due_at = expires_at - timedelta(days=_SECRET_ROTATION_BUFFER_DAYS)
        if days_left <= 0:
            warning_level = "critical"
            warning_message = "Secret is already expired; rotate immediately."
        elif days_left <= 30:
            warning_level = "critical"
            warning_message = "Secret expires within 30 days; rotate immediately."
        elif days_left <= 60:
            warning_level = "warn"
            warning_message = "Secret expires within 60 days; schedule rotation now."
        else:
            warning_level = "info"
            warning_message = "Secret lifetime is healthy; keep rotation schedule."

    return {
        "validity_policy": validity_policy,
        "issued_at": _isoformat_utc(issued_at),
        "expires_at": _isoformat_utc(expires_at),
        "rotation_due_at": _isoformat_utc(rotation_due_at),
        "warning_level": warning_level,
        "warning_message": warning_message,
    }


def _default_operator_notes() -> list[str]:
    return [
        "Canonical chat endpoint is POST /chat.",
        "POST /chatkit is a deprecated compatibility alias until 2026-04-04T00:00:00Z.",
        "Machine-readable capability negotiation endpoint is GET /integration-capabilities.",
        "Canonical host behavior is controlled by integration_manifest.host_policy.",
        "Thread creation resolution order: metadata.workflow_id -> metadata.project_id -> X-Project-Id.",
        "Do not use API key auth for public integrations; use OAuth client_credentials.",
    ]


def build_integration_manifest(
    *,
    base_url: str,
    partner_id: str | None = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
    default_chat_workflow_id: str | None = None,
    default_chat_workflow_readiness: str = "unknown",
    token_endpoint: str | None = None,
    scope: str | None = None,
    audience: str | None = None,
    allowed_domains: list[str] | None = None,
    rate_limit_profile: str | None = None,
    secret_expiry_months: int | None = None,
    secret_issued_at: str | None = None,
    secret_expires_at: str | None = None,
    host_policy: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or _utc_now()
    normalized_base_url = _base_url_without_trailing_slash(base_url)
    chat_api_url = f"{normalized_base_url}{_CHAT_API_PATH}"
    deprecated_chat_alias_url = f"{normalized_base_url}{_CHATKIT_ALIAS_PATH}"
    integration_capabilities_url = f"{normalized_base_url}{_INTEGRATION_CAPABILITIES_PATH}"

    normalized_scope = (scope or "").strip() or _DEFAULT_SCOPE
    normalized_tenant = (tenant_id or "").strip() or None
    normalized_project = (project_id or "").strip() or None
    normalized_default_workflow = (default_chat_workflow_id or "").strip() or None
    normalized_audience = (audience or "").strip() or None
    normalized_rate_limit = (rate_limit_profile or "").strip() or None
    resolved_allowed_domains = [
        domain.strip().lower()
        for domain in (allowed_domains or [])
        if isinstance(domain, str) and domain.strip()
    ]
    if not resolved_allowed_domains:
        host = _host_from_base_url(normalized_base_url)
        if host:
            resolved_allowed_domains = [host]
    manifest_host_policy = _normalize_manifest_host_policy(
        host_policy=host_policy,
        normalized_base_url=normalized_base_url,
        resolved_allowed_domains=resolved_allowed_domains,
        partner_id=partner_id,
    )

    issued_at = _parse_datetime(secret_issued_at)
    expires_at = _parse_datetime(secret_expires_at)
    policy_months = secret_expiry_months if isinstance(secret_expiry_months, int) and secret_expiry_months > 0 else None
    policy_text = (
        f"Partner secret validity policy: {policy_months} month(s). Rotate at least "
        f"{_SECRET_ROTATION_BUFFER_DAYS} days before expiry."
        if policy_months is not None
        else (
            "Partner secret validity policy: generated by onboarding profile. Rotate at least "
            f"{_SECRET_ROTATION_BUFFER_DAYS} days before expiry."
        )
    )

    manifest = {
        "api_base_url": normalized_base_url,
        "chat_api_url": chat_api_url,
        "integration_capabilities_url": integration_capabilities_url,
        "host_policy": manifest_host_policy,
        "deprecated_chat_alias_url": deprecated_chat_alias_url,
        "auth_profile": {
            "type": "oauth_client_credentials",
            "token_url": _token_endpoint_for_manifest(token_endpoint, normalized_tenant),
            "scope": normalized_scope,
            "audience": normalized_audience,
            "notes": [
                "Use Microsoft Entra OAuth2 client_credentials.",
                "Send Authorization: Bearer <access_token> on protected endpoints.",
            ],
        },
        "required_headers": [
            "Authorization",
            "X-Tenant-Id",
        ],
        "optional_headers": [
            "X-Project-Id",
            "X-Correlation-Id",
            "X-Trace-Id",
        ],
        "project_scope": {
            "tenant_id": normalized_tenant,
            "project_id": normalized_project,
            "default_chat_workflow_id": normalized_default_workflow,
            "default_chat_workflow_readiness": default_chat_workflow_readiness,
        },
        "deprecations": [
            {
                "endpoint": _CHATKIT_ALIAS_PATH,
                "status": "deprecated",
                "sunset_at": _isoformat_utc(_CHATKIT_ALIAS_SUNSET_AT),
                "remediation": "Migrate all integrations to POST /chat before sunset.",
            }
        ],
        "operator_notes": _default_operator_notes(),
        "allowed_domains": resolved_allowed_domains,
        "rate_limit_profile": normalized_rate_limit,
        "secret_expiry": _secret_expiry_payload(
            now=current_time,
            validity_policy=policy_text,
            issued_at=issued_at,
            expires_at=expires_at,
        ),
    }
    return manifest


def _require_string(
    payload: Mapping[str, Any],
    field: str,
    *,
    required: bool = False,
    max_length: int = 128,
    default: str = "",
) -> str:
    value = payload.get(field)
    if value is None:
        if required:
            raise PartnerSelfServiceError("INVALID_ARGUMENT", f"{field} is required", 422)
        return default
    if not isinstance(value, str):
        raise PartnerSelfServiceError("INVALID_ARGUMENT", f"{field} must be a string", 422)
    normalized = value.strip()
    if required and not normalized:
        raise PartnerSelfServiceError("INVALID_ARGUMENT", f"{field} is required", 422)
    if len(normalized) > max_length:
        raise PartnerSelfServiceError(
            "INVALID_ARGUMENT",
            f"{field} exceeds max length {max_length}",
            422,
        )
    if not normalized:
        return default
    return normalized


def _parse_allowed_domains(payload: Mapping[str, Any]) -> list[str]:
    raw_value = payload.get("allowed_domains")
    if raw_value is None:
        return []

    raw_items: list[Any]
    if isinstance(raw_value, str):
        raw_items = raw_value.split(",")
    elif isinstance(raw_value, list):
        raw_items = raw_value
    else:
        raise PartnerSelfServiceError("INVALID_ARGUMENT", "allowed_domains must be an array or comma-separated string", 422)

    domains: list[str] = []
    for item in raw_items:
        if not isinstance(item, str):
            raise PartnerSelfServiceError("INVALID_ARGUMENT", "allowed_domains entries must be strings", 422)
        candidate = item.strip().lower()
        if not candidate:
            continue
        if any(ch in candidate for ch in ("/", " ", "\t")):
            raise PartnerSelfServiceError("INVALID_ARGUMENT", "allowed_domains entries must be hostnames", 422)
        domains.append(candidate)

    deduped: list[str] = []
    seen: set[str] = set()
    for domain in domains:
        if domain in seen:
            continue
        seen.add(domain)
        deduped.append(domain)
    return deduped


def _parse_secret_expiry_months(payload: Mapping[str, Any]) -> int:
    raw_value = payload.get("secret_expiry_months", 12)
    if isinstance(raw_value, bool):
        raise PartnerSelfServiceError("INVALID_ARGUMENT", "secret_expiry_months must be an integer", 422)
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise PartnerSelfServiceError("INVALID_ARGUMENT", "secret_expiry_months must be an integer", 422) from exc
    if value < 1 or value > 24:
        raise PartnerSelfServiceError("INVALID_ARGUMENT", "secret_expiry_months must be in range 1..24", 422)
    return value


def _auto_partner_id(display_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "partner"
    digest = hashlib.sha1(display_name.encode("utf-8")).hexdigest()[:6]
    prefix_max_len = 63 - 1 - len(digest)
    prefix = slug[:prefix_max_len].strip("-_")
    if not prefix:
        prefix = "partner"
    candidate = f"{prefix}-{digest}"
    if not _PARTNER_ID_RE.match(candidate):
        raise PartnerSelfServiceError("INTERNAL", "failed to generate valid partner_id", 500)
    return candidate


def normalize_onboard_request(payload: Any, *, default_base_url: str = "https://api.hq21.tech") -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PartnerSelfServiceError("INVALID_ARGUMENT", "request body must be a JSON object", 422)

    display_name = _require_string(payload, "display_name", required=True, max_length=120)
    partner_id = _require_string(payload, "partner_id", max_length=64, default="")
    if not partner_id:
        partner_id = _auto_partner_id(display_name)
    if not _PARTNER_ID_RE.match(partner_id):
        raise PartnerSelfServiceError(
            "INVALID_ARGUMENT",
            "partner_id must match ^[a-z0-9][a-z0-9_-]{1,63}$",
            422,
        )

    tenant_id_pinned = _require_string(payload, "tenant_id_pinned", max_length=128, default=partner_id)
    entra_app_display_name = _require_string(
        payload,
        "entra_app_display_name",
        max_length=120,
        default=f"workcore-partner-{partner_id}",
    )
    rate_limit_profile = _require_string(payload, "rate_limit_profile", max_length=64, default="default")
    requested_host_policy = _require_string(payload, "host_policy", max_length=64, default="")
    allowed_domains = _parse_allowed_domains(payload)
    base_url = _require_string(payload, "base_url", max_length=200, default=default_base_url)
    if not (base_url.startswith("https://") or base_url.startswith("http://")):
        raise PartnerSelfServiceError("INVALID_ARGUMENT", "base_url must start with http:// or https://", 422)
    host_policy = resolve_partner_host_policy(
        partner_id=partner_id,
        requested_policy_id=requested_host_policy or None,
    )
    base_url, allowed_domains = apply_host_policy_to_target(
        base_url=base_url,
        allowed_domains=allowed_domains,
        host_policy=host_policy,
    )

    return {
        "partner_id": partner_id,
        "display_name": display_name,
        "entra_app_display_name": entra_app_display_name,
        "tenant_id_pinned": tenant_id_pinned,
        "allowed_domains": allowed_domains,
        "host_policy": host_policy,
        "status": "active",
        "rate_limit_profile": rate_limit_profile,
        "secret_expiry_months": _parse_secret_expiry_months(payload),
        "base_url": base_url,
    }


def decode_easyauth_principal(header_value: str) -> dict[str, Any]:
    encoded = header_value.strip()
    if not encoded:
        raise PartnerSelfServiceError("UNAUTHORIZED", "missing Entra principal header", 401)

    padded = encoded + ("=" * ((4 - len(encoded) % 4) % 4))
    try:
        decoded = base64.b64decode(padded.encode("ascii"))
    except Exception as exc:
        raise PartnerSelfServiceError("UNAUTHORIZED", "invalid Entra principal header encoding", 401) from exc

    try:
        payload = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise PartnerSelfServiceError("UNAUTHORIZED", "invalid Entra principal payload", 401) from exc

    if not isinstance(payload, dict):
        raise PartnerSelfServiceError("UNAUTHORIZED", "invalid Entra principal payload", 401)
    return payload


def _claim_value(claims: list[dict[str, Any]], *claim_types: str) -> str:
    wanted = {claim_type.lower() for claim_type in claim_types}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        claim_type = str(claim.get("typ", "")).strip().lower()
        if claim_type not in wanted:
            continue
        claim_value = str(claim.get("val", "")).strip()
        if claim_value:
            return claim_value
    return ""


def identity_from_easyauth_payload(payload: Mapping[str, Any]) -> PartnerPortalIdentity:
    claims = payload.get("claims")
    if not isinstance(claims, list):
        raise PartnerSelfServiceError("UNAUTHORIZED", "missing claims in Entra principal payload", 401)

    tenant_id = _claim_value(claims, "http://schemas.microsoft.com/identity/claims/tenantid", "tid")
    if not tenant_id:
        raise PartnerSelfServiceError("UNAUTHORIZED", "tenant claim is missing in Entra principal payload", 401)

    user_email = _claim_value(
        claims,
        "preferred_username",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn",
        "email",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
    )
    user_id = _claim_value(claims, "oid", "sub")
    if not user_id:
        user_id = user_email or "unknown"

    return PartnerPortalIdentity(tenant_id=tenant_id, user_id=user_id, user_email=user_email)


def render_partner_portal_html(context: Mapping[str, Any]) -> str:
    if not _PORTAL_TEMPLATE_PATH.exists():
        raise PartnerSelfServiceError("NOT_FOUND", "partner self-service portal template is missing", 404)

    template = _PORTAL_TEMPLATE_PATH.read_text(encoding="utf-8")
    marker = "__WORKCORE_PARTNER_PORTAL_CONTEXT__"
    if marker not in template:
        raise PartnerSelfServiceError("INTERNAL", "portal template marker is missing", 500)

    context_json = json.dumps(dict(context), ensure_ascii=True)
    return template.replace(marker, context_json)


def _build_partner_config(request_data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "partners": [
            {
                "partner_id": request_data["partner_id"],
                "display_name": request_data["display_name"],
                "entra_app_display_name": request_data["entra_app_display_name"],
                "entra_app_id": "",
                "tenant_id_pinned": request_data["tenant_id_pinned"],
                "allowed_domains": request_data["allowed_domains"],
                "host_policy": request_data.get("host_policy"),
                "status": "active",
                "rate_limit_profile": request_data["rate_limit_profile"],
                "secret_expiry_months": request_data["secret_expiry_months"],
            }
        ]
    }


def _sanitize_shell_output(output: str, max_length: int = 1000) -> str:
    sanitized_lines: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "client_secret" in line.lower() and ":" in line:
            continue
        sanitized_lines.append(line)
    combined = "\n".join(sanitized_lines)
    return combined[:max_length]


def _parse_onboard_script_output(stdout: str) -> dict[str, str]:
    values: dict[str, str] = {}
    secret_value = ""
    lines = stdout.splitlines()
    secret_marker = "Use this once-only client_secret value and deliver it via secure channel:"

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue

        if line == secret_marker:
            if index + 1 < len(lines):
                secret_value = lines[index + 1].strip()
            continue

        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        normalized_key = key.strip()
        value = raw_value.strip()
        if normalized_key in {
            "partner_id",
            "display_name",
            "client_id",
            "client_secret_expires_at",
            "token_endpoint",
            "scope",
        }:
            values[normalized_key] = value

    required_keys = [
        "partner_id",
        "display_name",
        "client_id",
        "client_secret_expires_at",
        "token_endpoint",
        "scope",
    ]
    missing = [key for key in required_keys if not values.get(key)]
    if missing or not secret_value:
        raise PartnerSelfServiceError(
            "UPSTREAM_FAILED",
            "partner onboarding automation returned unexpected output",
            502,
            {"missing_fields": missing, "secret_present": bool(secret_value)},
        )

    values["client_secret"] = secret_value
    return values


def run_partner_onboarding(
    request_data: Mapping[str, Any],
    *,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not _ONBOARD_SCRIPT_PATH.exists():
        raise PartnerSelfServiceError("INTERNAL", "partner onboarding script is missing", 500)

    if shutil.which("az") is None:
        raise PartnerSelfServiceError(
            "SERVICE_UNAVAILABLE",
            "Azure CLI is not available on this host",
            503,
        )

    temp_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
    temp_path = Path(temp_file.name)
    try:
        json.dump(_build_partner_config(request_data), temp_file)
        temp_file.flush()
        temp_file.close()

        env = dict(os.environ)
        env["PARTNERS_CONFIG_PATH"] = str(temp_path)
        env["PARTNER_ID"] = str(request_data["partner_id"])

        if extra_env:
            for key, value in extra_env.items():
                normalized_value = str(value).strip()
                if normalized_value:
                    env[key] = normalized_value

        completed = subprocess.run(
            [str(_ONBOARD_SCRIPT_PATH)],
            cwd=str(_ROOT_DIR),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass

    if completed.returncode != 0:
        details = {
            "stdout": _sanitize_shell_output(completed.stdout),
            "stderr": _sanitize_shell_output(completed.stderr),
        }
        raise PartnerSelfServiceError(
            "UPSTREAM_FAILED",
            "partner onboarding automation failed",
            502,
            details,
        )

    onboarding = _parse_onboard_script_output(completed.stdout)
    onboarding["base_url"] = str(request_data["base_url"])
    onboarding["tenant_id_pinned"] = str(request_data["tenant_id_pinned"])
    onboarding["allowed_domains"] = list(request_data.get("allowed_domains", []))
    onboarding["host_policy"] = dict(request_data.get("host_policy") or {})
    onboarding["rate_limit_profile"] = str(request_data.get("rate_limit_profile", "")).strip() or None
    onboarding["secret_expiry_months"] = request_data.get("secret_expiry_months")
    return onboarding


def build_onboarding_package_zip(onboarding: Mapping[str, Any], *, issued_by: str = "") -> bytes:
    partner_id = str(onboarding.get("partner_id", "")).strip()
    if not partner_id:
        raise PartnerSelfServiceError("INTERNAL", "cannot build package without partner_id", 500)

    base_url = str(onboarding.get("base_url", "https://api.hq21.tech")).strip() or "https://api.hq21.tech"
    tenant_id = str(onboarding.get("tenant_id_pinned", "")).strip() or "local"
    client_id = str(onboarding.get("client_id", "")).strip()
    client_secret = str(onboarding.get("client_secret", "")).strip()
    token_endpoint = str(onboarding.get("token_endpoint", "")).strip()
    scope = str(onboarding.get("scope", "")).strip()
    expires_at = str(onboarding.get("client_secret_expires_at", "")).strip()

    if not client_id or not client_secret or not token_endpoint or not scope:
        raise PartnerSelfServiceError("INTERNAL", "cannot build package without onboarding credentials", 500)

    generated_dt = _utc_now()
    generated_at = _isoformat_utc(generated_dt) or ""
    rate_limit_profile = str(onboarding.get("rate_limit_profile", "")).strip() or None
    secret_expiry_months_raw = onboarding.get("secret_expiry_months")
    secret_expiry_months = (
        int(secret_expiry_months_raw)
        if isinstance(secret_expiry_months_raw, int) and secret_expiry_months_raw > 0
        else None
    )
    allowed_domains = [str(item).strip() for item in onboarding.get("allowed_domains", []) if str(item).strip()]
    host_policy = onboarding.get("host_policy") if isinstance(onboarding.get("host_policy"), Mapping) else None

    integration_manifest = build_integration_manifest(
        base_url=base_url,
        partner_id=partner_id,
        tenant_id=tenant_id,
        token_endpoint=token_endpoint,
        scope=scope,
        allowed_domains=allowed_domains,
        rate_limit_profile=rate_limit_profile,
        secret_expiry_months=secret_expiry_months,
        secret_issued_at=generated_at,
        secret_expires_at=expires_at,
        default_chat_workflow_readiness="unknown",
        host_policy=host_policy,
    )
    secret_expiry = integration_manifest["secret_expiry"]
    resolved_host_policy = integration_manifest.get("host_policy", {})

    readme = "\n".join(
        [
            "# WorkCore Partner Onboarding Package",
            "",
            f"Generated at (UTC): {generated_at}",
            f"Generated by: {issued_by or 'internal-operator'}",
            f"Partner ID: {partner_id}",
            f"Pinned tenant: {tenant_id}",
            "",
            "## Canonical endpoints",
            f"- API base URL: {base_url}",
            f"- Canonical chat endpoint: {integration_manifest['chat_api_url']}",
            f"- Deprecated alias: {integration_manifest['deprecated_chat_alias_url']} (sunset at 2026-04-04T00:00:00Z)",
            f"- Host policy: {resolved_host_policy.get('policy_id')} ({resolved_host_policy.get('mode')}, {resolved_host_policy.get('enforcement')})",
            f"- Host policy canonical_base_url: {resolved_host_policy.get('canonical_base_url')}",
            f"- Host policy allowed_domains: {', '.join(resolved_host_policy.get('allowed_domains') or []) or 'n/a'}",
            "",
            "## Token exchange",
            f"POST {token_endpoint}",
            "grant_type=client_credentials",
            f"scope={scope}",
            "Decoded JWT note: `aud` may appear as the WorkCore resource app ID instead of the scope alias.",
            "This is expected as long as the token was requested with the scope above.",
            "",
            "## Secret lifetime",
            f"- client_secret_expires_at: {expires_at}",
            f"- rotation_due_at: {secret_expiry.get('rotation_due_at') or 'unknown'}",
            f"- warning_level: {secret_expiry.get('warning_level')}",
            f"- warning_message: {secret_expiry.get('warning_message')}",
            "",
            "## Bundle contents",
            "- .env.partner",
            "- integration_manifest.json",
            "- curl_examples/check_auth.sh",
            "- curl_examples/check_project_scope.sh",
            "- curl_examples/check_chat.sh",
            "",
            "## Verify access",
            "1. Load variables from `.env.partner`.",
            "2. Run `./curl_examples/check_auth.sh`.",
            "3. Set `PROJECT_ID` in `.env.partner`.",
            "4. Run `./curl_examples/check_project_scope.sh`.",
            "5. Run `./curl_examples/check_chat.sh`.",
            "",
            "## Security note",
            "- Treat `client_secret` as sensitive and deliver over secure channel only.",
            "- Do not paste client secrets into issue trackers, logs, or chat channels.",
        ]
    )

    env_content = "\n".join(
        [
            f"PARTNER_ID={partner_id}",
            f"BASE_URL={base_url}",
            "CHAT_API_URL=${BASE_URL}/chat",
            "DEPRECATED_CHAT_ALIAS_URL=${BASE_URL}/chatkit",
            f"TENANT_ID={tenant_id}",
            "PROJECT_ID=",
            f"CLIENT_ID={client_id}",
            f"CLIENT_SECRET={client_secret}",
            f"TOKEN_ENDPOINT={token_endpoint}",
            f"SCOPE={scope}",
            f"CLIENT_SECRET_EXPIRES_AT={expires_at}",
            f"SECRET_ROTATION_DUE_AT={secret_expiry.get('rotation_due_at') or ''}",
            f"SECRET_WARNING_LEVEL={secret_expiry.get('warning_level')}",
            f"SECRET_WARNING_MESSAGE={secret_expiry.get('warning_message')}",
            "",
            "# Decoded JWT note: `aud` may appear as the WorkCore resource app ID even when SCOPE uses the alias above.",
            "# Canonical chat endpoint is POST /chat. /chatkit is deprecated compatibility alias only.",
        ]
    )

    check_auth_script = """#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/.env.partner"

if [[ -z "${TOKEN_ENDPOINT:-}" || -z "${CLIENT_ID:-}" || -z "${CLIENT_SECRET:-}" || -z "${SCOPE:-}" ]]; then
  echo "missing required env values in .env.partner" >&2
  exit 1
fi

token_response="$(curl -sS -X POST "${TOKEN_ENDPOINT}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&scope=${SCOPE}")"

access_token="$(printf "%s" "${token_response}" | python3 -c 'import json,sys; print((json.load(sys.stdin) or {}).get("access_token",""))' 2>/dev/null || true)"

if [[ -z "${access_token}" || "${access_token}" == "null" ]]; then
  echo "auth_check=FAIL" >&2
  printf "%s\\n" "${token_response}" >&2
  exit 1
fi

echo "auth_check=PASS token_length=${#access_token}"
"""

    check_project_scope_script = """#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/.env.partner"

if [[ -z "${PROJECT_ID:-}" ]]; then
  echo "PROJECT_ID must be set in .env.partner before running project scope check" >&2
  exit 1
fi

token_response="$(curl -sS -X POST "${TOKEN_ENDPOINT}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&scope=${SCOPE}")"
access_token="$(printf "%s" "${token_response}" | python3 -c 'import json,sys; print((json.load(sys.stdin) or {}).get("access_token",""))' 2>/dev/null || true)"
if [[ -z "${access_token}" || "${access_token}" == "null" ]]; then
  echo "could not obtain access token for project scope check" >&2
  exit 1
fi

projects_json="$(curl -sS "${BASE_URL}/projects" \
  -H "Authorization: Bearer ${access_token}" \
  -H "X-Tenant-Id: ${TENANT_ID}")"

if printf "%s" "${projects_json}" | grep -q "\"project_id\"[[:space:]]*:[[:space:]]*\"${PROJECT_ID}\""; then
  echo "project_scope_check=PASS project_id=${PROJECT_ID}"
  exit 0
fi

echo "project_scope_check=FAIL project_id=${PROJECT_ID} not found in tenant=${TENANT_ID}" >&2
printf "%s\\n" "${projects_json}" >&2
exit 1
"""

    check_chat_script = """#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/.env.partner"

if [[ -z "${PROJECT_ID:-}" ]]; then
  echo "PROJECT_ID must be set in .env.partner before running chat check" >&2
  exit 1
fi

token_response="$(curl -sS -X POST "${TOKEN_ENDPOINT}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&scope=${SCOPE}")"
access_token="$(printf "%s" "${token_response}" | python3 -c 'import json,sys; print((json.load(sys.stdin) or {}).get("access_token",""))' 2>/dev/null || true)"
if [[ -z "${access_token}" || "${access_token}" == "null" ]]; then
  echo "could not obtain access token for chat check" >&2
  exit 1
fi

corr_id="corr-$(date -u +%Y%m%d%H%M%S)"
trace_id="trace-$(date -u +%Y%m%d%H%M%S)"
chat_response="$(curl -sS --max-time 25 -N -X POST "${CHAT_API_URL}" \
  -H "Authorization: Bearer ${access_token}" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Project-Id: ${PROJECT_ID}" \
  -H "X-Correlation-Id: ${corr_id}" \
  -H "X-Trace-Id: ${trace_id}" \
  -H "Content-Type: application/json" \
  -d '{"type":"threads.create","metadata":{"project_id":"'"${PROJECT_ID}"'"},"params":{"input":{"content":[{"type":"input_text","text":"integration doctor ping"}],"attachments":[],"inference_options":{}}}}')"

if printf "%s" "${chat_response}" | grep -q "data:"; then
  echo "chat_check=PASS endpoint=${CHAT_API_URL}"
  exit 0
fi

echo "chat_check=FAIL endpoint=${CHAT_API_URL}" >&2
printf "%s\\n" "${chat_response}" >&2
exit 1
"""

    metadata = {
        "generated_at": generated_at,
        "generated_by": issued_by or "internal-operator",
        "partner_id": partner_id,
        "tenant_id": tenant_id,
        "client_id": client_id,
        "scope": scope,
        "token_endpoint": token_endpoint,
        "base_url": base_url,
        "chat_api_url": integration_manifest["chat_api_url"],
        "deprecated_chat_alias_url": integration_manifest["deprecated_chat_alias_url"],
        "client_secret_expires_at": expires_at,
        "allowed_domains": allowed_domains,
        "host_policy": resolved_host_policy,
        "rate_limit_profile": rate_limit_profile,
        "secret_expiry": secret_expiry,
    }

    stream = BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", readme)
        archive.writestr(".env.partner", env_content)
        archive.writestr("integration_manifest.json", json.dumps(integration_manifest, ensure_ascii=True, indent=2, sort_keys=True))
        archive.writestr("curl_examples/check_auth.sh", check_auth_script)
        archive.writestr("curl_examples/check_project_scope.sh", check_project_scope_script)
        archive.writestr("curl_examples/check_chat.sh", check_chat_script)
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True))

    return stream.getvalue()
