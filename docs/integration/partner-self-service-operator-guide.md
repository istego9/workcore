# WorkCore Partner Self-Service Operator Guide

Date: 2026-03-05

This guide is for internal operators who provision partner API access through the built-in self-service portal.

## 1) Purpose
- Replace repetitive manual CLI onboarding steps with an internal Entra-protected portal.
- Generate a downloadable ZIP package (`README.md`, `.env.partner`, `metadata.json`) for partner delivery.

## 2) Portal endpoints
- `GET /internal/partner-access`
- `POST /internal/partner-access/onboard-package`

Both endpoints are internal-only and require Entra EasyAuth principal header `X-MS-CLIENT-PRINCIPAL`.

## 3) Required environment configuration
Set on orchestrator runtime:
- `WORKCORE_PARTNER_PORTAL_ENABLED=1`
- `WORKCORE_PARTNER_PORTAL_ALLOWED_TENANT_ID=<internal_entra_tenant_id>`

Recommended hardening:
- `WORKCORE_PARTNER_PORTAL_ALLOWED_USER_EMAILS=ops1@hq21.tech,ops2@hq21.tech`
- `WORKCORE_PARTNER_PORTAL_DEFAULT_BASE_URL=https://api.hq21.tech`

Optional Azure override variables used by onboarding automation:
- `AZ_RESOURCE_GROUP`
- `APIM_NAME`
- `APIM_OAUTH_AUDIENCE`
- `ENTRA_TENANT_ID`

## 4) Operator flow
1. Open internal portal page `GET /internal/partner-access`.
2. Fill minimum fields:
   - `partner_id`
   - `display_name`
   - `tenant_id_pinned`
3. Submit form with **Generate ZIP**.
4. Downloaded package contains:
   - `README.md` (token exchange and API call steps)
   - `.env.partner` (client credentials and endpoints)
   - `metadata.json` (non-secret package metadata)
5. Deliver package to partner over approved secure channel.

## 5) Error handling
- `401 UNAUTHORIZED`: no/invalid Entra principal header.
- `403 FORBIDDEN`: tenant or user is not allowed.
- `404 NOT_FOUND`: portal is disabled.
- `503 SERVICE_UNAVAILABLE`: Azure CLI is unavailable on runtime host.
- `502 UPSTREAM_FAILED`: onboarding script failed (Entra/APIM operation error).

## 6) Operational fallback
If portal is unavailable, use existing scripts directly:
- `./deploy/azure/scripts/apim_partner_onboard.sh`
- `./deploy/azure/scripts/apim_partner_rotate_secret.sh`
- `./deploy/azure/scripts/apim_partner_revoke.sh`
