# ADR-0013: Unified Partner Onboarding Bundle And Integration Doctor

Date: 2026-03-11
Status: Accepted

## Context
Partner onboarding previously exposed useful but fragmented surfaces:
- `/agent-integration-kit(.json)` for links and docs
- `/agent-integration-test(.json)` for basic readiness checks
- `/internal/partner-access/onboard-package` for a ZIP bundle

This created drift risk across docs/examples/package outputs and increased integration time for external teams.
At the same time, public chat contract policy is fixed:
- canonical endpoint: `POST /chat`
- deprecated alias: `POST /chatkit`
- sunset: `2026-04-04T00:00:00Z`

## Decision
Adopt one canonical integration manifest shape and one canonical doctor check model, while preserving existing endpoint URLs.

1. Manifest unification
- Define a normalized `integration_manifest` object.
- Reuse it in:
  - `GET /agent-integration-kit.json`
  - onboarding ZIP as `integration_manifest.json`

2. Doctor unification
- Upgrade `GET /agent-integration-test.json` to doctor-style checks with:
  - `status` (`PASS|WARN|FAIL`)
  - severity/code/title/message/remediation/docs reference
  - machine-readable observed vs expected values
- Keep legacy `description/ok/detail` fields for compatibility.

3. Canonical chat policy enforcement
- Manifest always advertises `/chat` as canonical.
- `/chatkit` can appear only as deprecated alias metadata with fixed sunset/remediation.
- Drift sentinel validates this policy across OpenAPI/docs/runtime integration surfaces.

4. Secret lifecycle surfacing
- Manifest includes secret expiry/rotation metadata and warning level so operators and partners can act before expiry windows.

## Compatibility strategy
- Additive changes only.
- Existing endpoint paths remain unchanged.
- Existing JSON consumers continue to parse old fields; new fields are additive.
- No reintroduction of API-key public auth; OAuth client_credentials remains the only public auth profile.

## Consequences
- Operators generate one canonical onboarding bundle instead of loose artifacts.
- Partners receive executable auth/project/chat smoke checks with canonical endpoint defaults.
- Integration diagnostics become explicit, actionable, and comparable across tenants/projects.
- CI catches drift where `/chatkit` is advertised as canonical or deprecation markers are missing.
