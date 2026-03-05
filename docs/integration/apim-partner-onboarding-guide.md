# WorkCore Partner Onboarding (Invite-Only)

Date: 2026-03-05

This guide is shared with invited partner teams after provisioning is completed by WorkCore platform operators.

## 1) Credentials package you receive
- `client_id`
- `client_secret` (one-time secret, valid for 12 months)
- `entra_tenant_id`
- `scope` (`api://workcore-partner-api/.default`)
- `base_url` (`https://api.hq21.tech` or `https://api.runwcr.com`)
- `tenant_id` (pinned tenant scope assigned by WorkCore platform)

## 2) How to get access token
```bash
curl -sS -X POST "https://login.microsoftonline.com/<entra_tenant_id>/oauth2/v2.0/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=<client_id>&client_secret=<client_secret>&scope=api://workcore-partner-api/.default"
```

Use `access_token` from response:
```bash
curl -sS "https://api.hq21.tech/projects" \
  -H "Authorization: Bearer <access_token>" \
  -H "X-Tenant-Id: <tenant_id>"
```

## 3) Required headers
- `Authorization: Bearer <access_token>`
- `X-Tenant-Id: <tenant_id>`
- `X-Project-Id` for `/workflows*` APIs
- `X-Correlation-Id` and `X-Trace-Id` are recommended

## 4) Common auth failures
- `401 UNAUTHORIZED`
  - token is missing/expired/invalid
  - app is not mapped as active partner in APIM
  - wrong scope/audience
- `403 FORBIDDEN`
  - app is disabled/revoked

## 5) Secret rotation and revoke
- Secret lifetime: 12 months.
- Rotation overlap window: 14 days.
- Rotation and revoke are handled by WorkCore platform operators through:
  - `deploy/azure/scripts/apim_partner_rotate_secret.sh`
  - `deploy/azure/scripts/apim_partner_revoke.sh`
