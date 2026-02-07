---
name: security-governance
description: Implement security foundations: authN/authZ, RBAC, secrets management, audit logs, PII redaction, and secure webhooks. Use when introducing authentication/authorization, tenants, secrets, or enterprise controls.
---

# Security Governance

## Requirements
- Enforce RBAC on workflows/runs/webhooks/secrets.
- Store secrets only in a secrets manager.
- Emit audit logs for privileged actions (publish, rollback, secret changes).
- Redact sensitive payloads in logs by default.

## Steps
1) Define RBAC roles and a permissions matrix.
2) Implement auth middleware and policy checks.
3) Implement secrets abstraction (read at runtime, never return in API).
4) Implement audit log events and a query API.
5) Harden webhooks:
   - Signature verification
   - Replay protection
   - Rate limiting

## Definition of done
- Secrets cannot be exfiltrated via APIs or logs.
- Admin actions are auditable.
- Webhook endpoints reject unsigned or replayed requests.
