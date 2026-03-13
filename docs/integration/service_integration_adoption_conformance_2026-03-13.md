# Service Integration Adoption / Conformance (2026-03-13)

## Classification
- Task class: `E` (external integration behavior change in consuming service)
- Spec-first impact: no public WorkCore API contract/schema changes planned in this task; changes are consumer-side conformance updates in Builder chat clients.

## Goal and scope
Align Builder-side WorkCore consumption with the canonical integration contract:
- canonical `POST /chat` usage
- project-scoped chat resolution support
- onboarding/manifest-driven host+auth bootstrap
- integration capabilities bootstrap
- typed error handling and retry policy
- correlation/trace header propagation and safe observability
- doctor gate handling (`/agent-integration-test.json`)

## Conformance inventory (before)
WorkCore touchpoints found in this repository (consumer-side):
- Chat surfaces:
  - `apps/builder/src/chat-fork/App.tsx`
  - `apps/builder/src/chat-fork/api/chatkit-client.ts`
  - `apps/builder/public/chatkit.html`
  - `apps/builder/src/App.tsx` (chat deep-link generation)
- Run start endpoint:
  - `apps/builder/src/api.ts` (`POST /workflows/{workflow_id}/runs`)
- Onboarding/kit surfaces already linked:
  - `apps/builder/src/integration-kit.ts` (`/agent-integration-kit*`, `/agent-integration-test*`)

## Contract gaps found (before)
1. Typed error handling in `chat-fork` is string-based; typed fields are not consumed.
2. `chat-fork` request headers do not include `X-Correlation-Id` / `X-Trace-Id`; `X-Project-Id` is not propagated as header.
3. No integration capabilities bootstrap or caching in chat clients.
4. No doctor gate handling before considering integration ready.
5. No host policy enforcement from `integration_manifest.host_policy`.
6. Legacy `/chatkit` endpoint usage is not centrally detected/reported at runtime (consumer-side metric/alert path missing).
7. `chatkit.html` connect flow requires `workflow_id` only (project-only scope not accepted).
8. Builder chat deep-link generation requires selected workflow and does not allow project-only chat entry.

## Action items
1. Implement manifest/capabilities/doctor bootstrap in chat clients.
2. Enforce canonical `/chat` URL resolution with explicit legacy alias rewrite + internal alert event.
3. Add typed error model parsing and retry policy (`retryable`, `retry_after_s` / `Retry-After`).
4. Add required/recommended headers: `Authorization`, `X-Tenant-Id`, `X-Correlation-Id`, `X-Trace-Id`, `X-Project-Id`.
5. Enable project-scoped connect path (`workflow_id` optional when `project_id` exists).
6. Update env defaults toward canonical chat URL.
7. Add/adjust unit tests for bootstrap + typed error/retry/header behavior.
8. Update operator runbook with doctor/capabilities/header checks.

## Compatibility strategy
- Additive and backward-compatible where practical:
  - Keep env alias compatibility (`VITE_CHATKIT_*`) while preferring canonical vars.
  - Continue supporting workflow-scoped flow while adding project-scoped fallback.
  - Keep existing UI pages; harden runtime behavior without redesign.

## Observability/security
- Add safe client logs with endpoint/correlation/trace/error code/category.
- Do not log bearer tokens, secrets, or raw sensitive payloads.

## Rollout/rollback notes
- Rollout: deploy Builder changes; monitor legacy alias alert events and typed error telemetry.
- Rollback: restore prior client behavior by reverting Builder chat client changes only (no server contract migration required).

## Outstanding TODOs/questions
- None blocking for consumer-side conformance implementation in this repository.

## Implementation summary (after)
Implemented in this repository:
1. Chat bootstrap from WorkCore onboarding surfaces:
   - Added `apps/builder/src/chat-fork/api/integration-bootstrap.ts`
   - Bootstrap now reads:
     - `GET /agent-integration-kit.json`
     - `GET /integration-capabilities` (cached)
     - `GET /agent-integration-test.json` (project-scoped when available)
2. Host policy + canonical chat enforcement:
   - Canonical chat URL resolved to `/chat`.
   - Pinned host policy (`mode=pinned`, `enforcement=required`) is enforced client-side.
3. Legacy alias controls:
   - Runtime rewrite `/chatkit` -> `/chat` with explicit internal alert event:
     - `workcore.integration.legacy_chat_alias_used`
4. Typed error handling and retry policy:
   - Added typed error parsing (`code`, `message`, `category`, `retryable`, `retry_after_s`, `bad_fields`, `unsupported_feature`, `docs_ref`, `correlation_id`).
   - Retry now occurs only when `retryable=true`, with backoff from `retry_after_s` / `Retry-After`.
5. Headers and observability:
   - Chat client sends `Authorization`, `X-Tenant-Id`, `X-Correlation-Id`, `X-Trace-Id`, `X-Project-Id`.
   - Safe logs include endpoint + correlation/trace + typed error code/category (no token logging).
6. Project-scoped chat adoption:
   - `chatkit.html` connect now accepts either `workflow_id` or `project_id`.
   - Builder deep-link generation no longer hard-requires workflow when project scope is present.
7. Doctor gate:
   - If doctor report contains `FAIL`, chat integration is not marked ready.
8. Config/runbook updates:
   - Canonical env var `VITE_CHAT_API_URL` added; alias `VITE_CHATKIT_API_URL` retained for compatibility.
   - Runbook updated with capabilities/doctor/header/host-policy checks.

## Verification (after)
- Unit tests:
  - `cd apps/builder && npm run test:unit`
- Targeted e2e:
  - `cd apps/builder && npm run test:e2e -- e2e/chatkit-ui.spec.ts e2e/chat-fork-ui.spec.ts`
- Repository checks:
  - `./scripts/archctl_validate.sh` (fallback validation path used because `archctl` binary unavailable)
  - `./scripts/dev_check.sh`

Result: all executed checks passed.
