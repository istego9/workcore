# ADR-0014: Typed Error Contract and Capability Negotiation Surface

Date: 2026-03-11  
Status: Accepted

## Context
External integrators currently rely on partially divergent error payloads across public surfaces (`/chat`, `/chatkit`, `/orchestrator/messages`, run start, handoff APIs).  
`/capabilities` already serves a different purpose: tenant-scoped versioned capability contract registry.

This caused two contract issues:
- clients had to parse free-text or endpoint-specific error shapes to decide retry/validation/remediation behavior;
- there was no single read-only machine-readable endpoint for platform feature negotiation.

## Decision
1. Introduce additive shared public error schemas:
   - `PlatformError`
   - `PlatformErrorEnvelope`

2. Keep backward compatibility:
   - preserve `error.code`, `error.message`, and top-level `correlation_id`;
   - keep `ErrorEnvelope` as a compatibility alias over `PlatformErrorEnvelope`.

3. Adopt typed error fields on major integration surfaces:
   - `POST /chat`
   - `POST /chatkit` (deprecated alias, unchanged lifecycle)
   - `POST /orchestrator/messages`
   - `POST /workflows/{workflow_id}/runs`
   - `POST /handoff/packages`

4. Align orchestrator route/action policy errors:
   - `OrchestratorActionError := PlatformError + required { action }`.

5. Add separate read-only negotiation endpoint:
   - `GET /integration-capabilities`
   - public (`security: []`)
   - intentionally generic and non-tenant-specific.

6. Keep namespace boundaries explicit:
   - `/capabilities*` remains registry CRUD/listing for versioned capability contracts.
   - `/integration-capabilities` is negotiation/discovery only.

7. Wire negotiation URL into onboarding/discovery bundles:
   - include `integration_capabilities_url` in `/agent-integration-kit.json` manifest payload;
   - include the same field in onboarding package `integration_manifest.json`.

## Consequences
### Positive
- Integrators get one typed, additive error contract with stable machine-readable categories.
- Retry/backoff behavior becomes explicit (`retryable`, `retry_after_s`, optional `Retry-After`).
- Public feature negotiation no longer depends on onboarding doctor output or free-text docs.

### Neutral/Tradeoff
- Error payloads become larger due to additive typed fields.
- Drift checks must enforce the new surface and schema alignment.

### Compatibility
- Additive/non-breaking for existing consumers parsing only `error.code`, `error.message`, and `correlation_id`.
- `/chat` remains canonical; `/chatkit` remains deprecated compatibility alias until sunset.
