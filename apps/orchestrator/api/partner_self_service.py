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
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

_ROOT_DIR = Path(__file__).resolve().parents[3]
_ONBOARD_SCRIPT_PATH = _ROOT_DIR / "deploy" / "azure" / "scripts" / "apim_partner_onboard.sh"
_PORTAL_TEMPLATE_PATH = _ROOT_DIR / "docs" / "integration" / "partner-self-service-portal.html"
_PARTNER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_EPAM_MARKER = "epam"
_EPAM_BASE_URL = "https://api.runwcr.com"
_EPAM_ALLOWED_DOMAINS = ["api.runwcr.com"]


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


def _contains_epam_marker(value: str) -> bool:
    return _EPAM_MARKER in value.strip().lower()


def _is_epam_partner(*values: str) -> bool:
    return any(_contains_epam_marker(value) for value in values if value)


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
    allowed_domains = _parse_allowed_domains(payload)
    base_url = _require_string(payload, "base_url", max_length=200, default=default_base_url)
    if not (base_url.startswith("https://") or base_url.startswith("http://")):
        raise PartnerSelfServiceError("INVALID_ARGUMENT", "base_url must start with http:// or https://", 422)
    if _is_epam_partner(display_name, partner_id, tenant_id_pinned, entra_app_display_name):
        base_url = _EPAM_BASE_URL
        allowed_domains = list(_EPAM_ALLOWED_DOMAINS)

    return {
        "partner_id": partner_id,
        "display_name": display_name,
        "entra_app_display_name": entra_app_display_name,
        "tenant_id_pinned": tenant_id_pinned,
        "allowed_domains": allowed_domains,
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

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    readme = "\n".join(
        [
            "# WorkCore Partner Onboarding Package",
            "",
            f"Generated at (UTC): {generated_at}",
            f"Generated by: {issued_by or 'internal-operator'}",
            f"Partner ID: {partner_id}",
            f"Pinned tenant: {tenant_id}",
            "",
            "## Token exchange",
            f"POST {token_endpoint}",
            "grant_type=client_credentials",
            f"scope={scope}",
            "Decoded JWT note: `aud` may appear as the WorkCore resource app ID instead of the scope alias.",
            "This is expected as long as the token was requested with the scope above.",
            "",
            "## API base URL",
            f"{base_url}",
            "",
            "## Verify access",
            "1. Load variables from `.env.partner`.",
            "2. Request an access token.",
            "3. Call `GET /projects` with `Authorization: Bearer <token>`.",
            "",
            "## Secret lifetime",
            f"client_secret_expires_at={expires_at}",
            "",
            "## Security note",
            "- Treat `client_secret` as sensitive and deliver over secure channel only.",
        ]
    )

    env_content = "\n".join(
        [
            f"PARTNER_ID={partner_id}",
            f"BASE_URL={base_url}",
            f"TENANT_ID={tenant_id}",
            f"CLIENT_ID={client_id}",
            f"CLIENT_SECRET={client_secret}",
            f"TOKEN_ENDPOINT={token_endpoint}",
            f"SCOPE={scope}",
            f"CLIENT_SECRET_EXPIRES_AT={expires_at}",
            "",
            "# Decoded JWT note: `aud` may appear as the WorkCore resource app ID even when SCOPE uses the alias above.",
            "# Example:",
            "# TOKEN=$(curl -sS -X POST \"$TOKEN_ENDPOINT\" \\",
            "#   -H \"Content-Type: application/x-www-form-urlencoded\" \\",
            "#   -d \"grant_type=client_credentials&client_id=$CLIENT_ID&client_secret=$CLIENT_SECRET&scope=$SCOPE\" | jq -r '.access_token')",
            "# curl -sS \"$BASE_URL/projects\" -H \"Authorization: Bearer $TOKEN\" -H \"X-Tenant-Id: $TENANT_ID\"",
        ]
    )

    metadata = {
        "generated_at": generated_at,
        "generated_by": issued_by or "internal-operator",
        "partner_id": partner_id,
        "tenant_id": tenant_id,
        "client_id": client_id,
        "scope": scope,
        "token_endpoint": token_endpoint,
        "base_url": base_url,
        "client_secret_expires_at": expires_at,
        "allowed_domains": list(onboarding.get("allowed_domains", [])),
    }

    stream = BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", readme)
        archive.writestr(".env.partner", env_content)
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True))

    return stream.getvalue()
