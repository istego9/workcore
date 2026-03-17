# HQ21 Integration Playbook (WorkCore v1)

## Scope
Operational integration guidance for HQ21 backend/client teams using WorkCore workflow/run APIs and ChatKit interactions.

## Base contract
- Source of truth: `docs/api/openapi.yaml`
- Usage guide: `docs/api/reference.md`
- Conventions: `docs/api/conventions.md`

## Gateway endpoints
- Default public API host: `https://api.hq21.tech`
- Some onboarding bundles may pin `integration_manifest.host_policy.canonical_base_url` to `https://api.runwcr.com`.
- Treat host selection as policy-driven contract from onboarding/doctor surfaces, not as a host-role taxonomy.
- Contract, headers, auth, and payload semantics stay identical for any host explicitly allowed by `integration_manifest.host_policy`.

## Bootstrap and conformance
Before enabling production traffic:
1. Fetch `GET /agent-integration-kit.json` and persist the current `integration_manifest` for the target environment.
2. Fetch `GET /integration-capabilities` and use it as the machine-readable capability contract.
3. Run `GET /agent-integration-test.json` and treat any `FAIL` check as a launch blocker.
4. Enforce canonical host selection from `integration_manifest.host_policy`.
5. Treat `POST /chat` as canonical and `/chatkit` only as deprecated compatibility alias until `2026-04-04T00:00:00Z`.

## Required headers and identity propagation
For all workflow/run operations send:
- `X-Tenant-Id`
- `X-Correlation-Id`
- `X-Trace-Id`

Recommended:
- `X-Project-Id`
- `X-Import-Run-Id`
- `X-User-Id`
- `Idempotency-Key` for mutating requests

For ChatKit (`POST /chat`) include integration metadata in request body:
- `metadata.workflow_id` (optional explicit workflow override on `threads.create`)
- `metadata.project_id` (optional project scope for project-centric `threads.create`)
- `metadata.workflow_version_id` (optional)
- `metadata.external_user_id` (recommended)
- `metadata.external_session_id` (recommended)

Deprecated compatibility alias:
- `POST /chatkit` remains available until `2026-04-04T00:00:00Z`
- alias responses include `Deprecation: true` and `Sunset: Sat, 04 Apr 2026 00:00:00 GMT`
- on/after `2026-04-04T00:00:00Z` alias returns `410 Gone`

## Field mapping (HQ21 -> WorkCore)
Minimum run-start mapping:
- `tenant_id` -> `X-Tenant-Id`
- `project_id` -> `X-Project-Id`
- `import_run_id` -> `X-Import-Run-Id`
- request correlation -> `X-Correlation-Id`
- request trace -> `X-Trace-Id`
- actor/user -> `metadata.user_id`

Run correlation storage in HQ21:
- Persist WorkCore `run_id` as `workcore_run_id`.
- Persist `workflow_id` and `version_id` for audit and replay.

## Recommended integration sequence
1. Create or fetch target workflow.
2. Publish workflow version.
3. If using direct orchestrator routing, register workflow routing metadata:
   - `POST /projects/{project_id}/workflow-definitions`
4. If using direct orchestrator routing, read back the routing registration before smoke/cutover:
   - `GET /projects/{project_id}/workflow-definitions/{workflow_id}`
5. If using project-scoped chat, confirm `projects.settings.default_chat_workflow_id` points to the published workflow.
6. Start user interaction via chat:
   - `POST /chat` with `type=threads.create`
   - persist returned `thread_id`
7. Continue user interaction via chat:
   - `type=threads.add_user_message` for regular messages
   - `type=threads.custom_action` for widget actions (approve/reject/submit)
   - pass action idempotency key in payload when available
8. Track run status via:
   - `GET /runs/{run_id}`
   - `GET /runs/{run_id}/stream` (SSE)
9. Use webhook fallback for delayed consumers:
   - outbound subscriptions to `interrupt_created`, `run_completed`, `run_failed`, `node_failed`

## Retry policy
Use idempotency-safe retries for mutating calls:
- Retry classes: network errors, timeout, `5xx`, `429`, or typed platform errors with `error.retryable=true`.
- Backoff: exponential + jitter, honoring `error.retry_after_s` or HTTP `Retry-After` when present.
- Respect idempotency key reuse for same logical operation.
- Surface typed error fields in logs/alerts:
  - `error.code`
  - `error.category`
  - `error.bad_fields`
  - `error.docs_ref`
  - `correlation_id`

Do not auto-retry:
- Validation failures (`400`, `PRECONDITION_FAILED`)
- Auth failures (`401`, `403`) before config fix

## Rollback and failure handling
1. If new workflow version is faulty:
   - rollback draft to active version (`POST /workflows/{workflow_id}/rollback`)
   - republish corrected version
2. If run fails:
   - inspect `GET /runs/{run_id}` with focus on:
     - top-level `error`, `last_error`, `failed_node_id`
     - `node_runs[].last_error` (or `node_states[]` alias for legacy clients)
   - inspect `GET /runs/{run_id}/ledger` for `node_failed`/`run_failed` payload diagnostics (`step_id`/`node_id`, `payload.error`)
   - rerun specific node when safe (`POST /runs/{run_id}/rerun-node`)
3. If integration outage occurs:
   - pause external trigger/source
   - recover service health
   - replay with idempotency keys

## Validation checklist before production
1. Auth and tenant headers are enforced.
2. `GET /integration-capabilities` is consumed by the client/bootstrap layer.
3. Latest doctor report from `GET /agent-integration-test.json` has no `FAIL` checks.
4. Host selection follows `integration_manifest.host_policy`.
5. Typed platform errors are parsed and only `retryable=true` failures are retried.
6. Idempotency behavior verified for retries.
7. SSE reconnect tested with `Last-Event-ID`.
8. Chat thread create/message/action flow tested end-to-end.
9. Interrupt resume path tested through chat widget/action and direct API fallback.
10. For direct orchestrator routing, workflow-definition readback is confirmed after bind.
11. Runbook and incident SOP available to on-call.

## References
- Runbook: `docs/runbooks/orchestrator-runtime.md`
- Runbook: `docs/runbooks/chatkit-integration.md`
- Runbook: `docs/runbooks/streaming-sse.md`
- Runbook: `docs/runbooks/webhooks-delivery.md`
- Runbook: `docs/runbooks/workflow-release-pipeline.md`
- Postmortem template: `docs/postmortems/template.md`
