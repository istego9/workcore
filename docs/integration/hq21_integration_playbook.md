# HQ21 Integration Playbook (WorkCore v1)

## Scope
Operational integration guidance for HQ21 backend/client teams using WorkCore workflow/run APIs and ChatKit interactions.

## Base contract
- Source of truth: `docs/api/openapi.yaml`
- Usage guide: `docs/api/reference.md`
- Conventions: `docs/api/conventions.md`

## Gateway endpoints
- Primary API host: `https://api.hq21.tech`
- Optional alias host: `https://api.runwcr.com`
- Both hosts route to the same backend gateway path (Cloudflare/Front Door). Treat alias as hostname-level routing option, not a separate runtime mode.
- Contract, headers, auth, and payload semantics are identical across both hosts.

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
3. Start user interaction via chat:
   - `POST /chat` with `type=threads.create`
   - persist returned `thread_id`
4. Continue user interaction via chat:
   - `type=threads.add_user_message` for regular messages
   - `type=threads.custom_action` for widget actions (approve/reject/submit)
   - pass action idempotency key in payload when available
5. Track run status via:
   - `GET /runs/{run_id}`
   - `GET /runs/{run_id}/stream` (SSE)
6. Use webhook fallback for delayed consumers:
   - outbound subscriptions to `interrupt_created`, `run_completed`, `run_failed`, `node_failed`

## Retry policy
Use idempotency-safe retries for mutating calls:
- Retry classes: network errors, timeout, `5xx`, `429`.
- Backoff: exponential + jitter.
- Respect idempotency key reuse for same logical operation.

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
2. Idempotency behavior verified for retries.
3. SSE reconnect tested with `Last-Event-ID`.
4. Chat thread create/message/action flow tested end-to-end.
5. Interrupt resume path tested through chat widget/action and direct API fallback.
6. Runbook and incident SOP available to on-call.

## References
- Runbook: `docs/runbooks/orchestrator-runtime.md`
- Runbook: `docs/runbooks/chatkit-integration.md`
- Runbook: `docs/runbooks/streaming-sse.md`
- Runbook: `docs/runbooks/webhooks-delivery.md`
- Postmortem template: `docs/postmortems/template.md`
