# Security Baseline

## Purpose
Define repository-level security controls that must remain true across features and refactors.
This file is a control index; detailed behavior stays in API/architecture docs and runbooks.

## System of record
- Root policy: `AGENTS.md`
- API security conventions: `docs/api/conventions.md`
- API usage details: `docs/api/reference.md`
- Runtime behavior: `docs/architecture/runtime.md`, `docs/architecture/executors.md`
- Webhook operations: `docs/runbooks/webhooks-delivery.md`
- Incident handling: `docs/postmortems/template.md`

## Non-negotiable controls
1. No secrets in repository, tests, or logs.
2. API auth is enforced when `WORKCORE_API_AUTH_TOKEN` is configured.
3. Inbound webhook signatures are validated using `WEBHOOK_DEFAULT_INBOUND_SECRET` or registered integration secrets.
4. CORS must be an explicit allowlist; wildcard origins are not allowed in secure startup profiles.
5. `integration_http` executor egress is deny-by-default and constrained by environment policy:
   - `INTEGRATION_HTTP_ALLOWED_HOSTS`
   - `INTEGRATION_HTTP_ALLOW_PRIVATE_NETWORKS` (default secure posture is disabled/false)
6. Changes that affect contracts, persistence, runtime events, or boundaries follow Spec-First control from `AGENTS.md`.

## PR security checklist
- [ ] No credentials/tokens added to code, docs examples, or fixtures.
- [ ] Security-sensitive behavior has tests (auth, signature, policy enforcement, input validation).
- [ ] Public API/security docs were updated when behavior changed.
- [ ] New logs avoid sensitive payload leakage by default.
- [ ] Rollout/rollback notes include security impact for risky changes.

## Escalation rules
Stop and escalate when:
- required security constraints are unclear,
- requested behavior conflicts with existing security guarantees,
- environment policy inputs are missing for sensitive paths (auth, webhook verification, outbound egress).
