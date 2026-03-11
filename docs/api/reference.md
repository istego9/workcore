# WorkCore API Reference (v1)

This guide explains how to use the WorkCore API as an orchestration layer for HQ21.

Primary contract source: `/openapi.yaml` (OpenAPI 3.0.3).

## Base URL
- Local (Docker + local domain): `https://api.workcore.build`
- Local (direct service): `http://127.0.0.1:8000`
- Production: use your deployed API URL.

## Authentication
- Public API access is provided through Azure API Management (APIM) with Microsoft Entra OAuth2 (`client_credentials`).
- Exchange `client_id` + `client_secret` for an access token:
  - `POST https://login.microsoftonline.com/<tenant_id>/oauth2/v2.0/token`
  - `grant_type=client_credentials`
  - `scope=api://workcore-partner-api/.default`
- Send:
  - `Authorization: Bearer <access_token>`
- JWT note:
  - decoded access tokens may show `aud` as the WorkCore resource app ID instead of the scope alias
  - this is expected if the token was requested with `scope=api://workcore-partner-api/.default`

Example token exchange:
```bash
curl -sS -X POST "https://login.microsoftonline.com/<tenant_id>/oauth2/v2.0/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=<client_id>&client_secret=<client_secret>&scope=api://workcore-partner-api/.default"
```
- No OAuth token is required for:
  - `GET /health`
  - `GET /openapi.yaml`
  - `GET /api-reference`
  - `GET /integration-capabilities`
  - `GET /workflow-authoring-guide`
  - `GET /agent-integration-kit`
  - `GET /agent-integration-kit.json`
  - `GET /agent-integration-test`
  - `GET /agent-integration-test.json`
  - `POST /agent-integration-test/validate-draft`
  - `GET /schemas/*`
  - `POST /webhooks/inbound/{integration_key}` (signature-based)

Inbound webhooks require signature headers generated with `WEBHOOK_DEFAULT_INBOUND_SECRET`:
- `X-Webhook-Timestamp`
- `X-Webhook-Signature`

APIM validates OAuth token, pins tenant scope by partner mapping, and forwards internal bearer credentials to upstream services.

### Internal partner onboarding self-service
- Internal operator portal endpoint: `GET /internal/partner-access`
- Package generation endpoint: `POST /internal/partner-access/onboard-package`
- Intended usage:
  - operator signs in through Microsoft Entra protected internal frontend
  - frontend forwards EasyAuth principal header `X-MS-CLIENT-PRINCIPAL`
  - backend validates Entra principal and returns onboarding ZIP package
- Minimal required input in portal form:
  - `display_name`
- Auto-generated defaults (can be overridden in advanced fields):
  - `partner_id` generated from `display_name`
  - `tenant_id_pinned` defaults to generated `partner_id`
- Partner-specific onboarding host policy:
  - host behavior is explicit via `host_policy` (first-class contract), not name markers
  - for `partner_id=epam_future-insurance`, policy `pinned_runwcr` is enforced
  - generated onboarding artifacts are pinned to `BASE_URL=https://api.runwcr.com`
  - `allowed_domains` are normalized to `api.runwcr.com` only
- ZIP package includes:
  - `README.md` with partner-specific token exchange and integration doctor guidance
  - `.env.partner` with partner-specific environment values (`client_id`, `client_secret`, `scope`, `token_endpoint`, `base_url`)
  - `integration_manifest.json` (canonical machine-readable manifest reused by `/agent-integration-kit.json`)
  - `curl_examples/check_auth.sh`
  - `curl_examples/check_project_scope.sh`
  - `curl_examples/check_chat.sh`
  - `metadata.json` (backward-compatible package metadata)

## Required integration headers
- `X-Tenant-Id`: tenant scope for all workflow/run operations.
- `X-Tenant-Id` is required for `POST /chat` in strict multi-tenant mode.
- `X-Correlation-Id`: request correlation key; echoed in responses/errors.
- `X-Trace-Id`: distributed trace key; propagated to run metadata/events.
- `X-Project-Id`: required for all `/workflows*` authoring/read operations.
- `X-Project-Id` is not required for `GET /projects` and `POST /projects`.

Optional headers:
- `X-Import-Run-Id`
- `X-User-Id`
- `Idempotency-Key` (recommended for mutating APIs)

## Error envelope
Public integration endpoints use additive typed platform errors:

```json
{
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "...",
    "category": "validation",
    "retryable": false,
    "retry_after_s": null,
    "bad_fields": null,
    "unsupported_feature": null,
    "docs_ref": null,
    "details": null,
    "correlation_id": "corr_123"
  },
  "correlation_id": "corr_123"
}
```

Compatibility guarantees:
- Existing consumers of `error.code`, `error.message`, and top-level `correlation_id` continue to work unchanged.
- Typed fields are additive and may be `null` when not known.

Category taxonomy:
- `auth`
- `validation`
- `configuration`
- `not_found`
- `conflict`
- `unsupported_feature`
- `transient`
- `internal`
- `route`
- `action`

Retry semantics:
- When `error.retryable=true`, clients should treat error as retry-eligible.
- If backoff is known, server sets `error.retry_after_s` and may emit HTTP `Retry-After` (for example on `429`/`503`).

## JSON schemas for workflow authoring
- Draft payload schema: `docs/api/schemas/workflow-draft.schema.json`
- Builder import/export schema (`workflow_export_v1`): `docs/api/schemas/workflow-export-v1.schema.json`
- Orchestrator strict routing schema: `docs/api/schemas/routing-decision.schema.json`

## Set State batch assignments
`set_state` supports two compatible config styles:
- Legacy single assignment:
  - `target` + `expression`
- Batch assignments:
  - `assignments[]` with items `{ "target": "...", "expression": "..." }`

Runtime applies `assignments[]` in order when present. If `assignments[]` is missing, runtime falls back to legacy `target` + `expression`.

## Integration HTTP node (`integration_http`)
Use `integration_http` for non-MCP external API calls directly in workflow runtime.

Supported config fields:
- `url` (required)
- `method` (`GET|POST|PUT|PATCH|DELETE`, default `GET`)
- `headers` (optional object)
- `auth` (optional object):
  - `type`: `none|bearer|basic`
  - `token` or `token_env` (for bearer)
  - `username/password` or `username_env/password_env` (for basic)
- `timeout_s` (optional, default runtime value)
- `retry_attempts` and `retry_backoff_s` (optional)
- `request_body_expression` (optional expression evaluated against `inputs/state/node_outputs`)
- `response_state_target` (optional state path for full response envelope)
- `response_body_state_target` (optional state path for response body)
- `fail_on_status` (optional bool, default `true`)
- `allowed_statuses` (optional list of HTTP status codes)

Runtime egress policy:
- `INTEGRATION_HTTP_ALLOWED_HOSTS` (required allowlist for executor traffic, comma-separated).
- `INTEGRATION_HTTP_ALLOWED_SCHEMES` (optional, default `https`).
- `INTEGRATION_HTTP_ALLOW_PRIVATE_NETWORKS` (optional, default `false`).
- `INTEGRATION_HTTP_DENY_CIDRS` (optional CIDR deny overlay for resolved target IPs, comma-separated).

Resolution behavior:
- For hostname targets, runtime resolves DNS and validates each resolved IP against private/local restrictions.
- When `INTEGRATION_HTTP_DENY_CIDRS` is configured, resolved IPs matching any listed CIDR are always blocked.

## Artifact references and run projections
For document-heavy workflows, prefer artifact references over inline binary payloads.

Run start (`POST /workflows/{workflow_id}/runs`) supports:
- `inputs.documents[].pages[].artifact_ref` as preferred page-content carrier.
- `state_exclude_paths: string[]` to exclude heavy paths from persisted/returned run state.
- `output_include_paths: string[]` to return only required output paths.

Compatibility:
- Inline fields (for example `image_base64`) are still accepted during migration.

Projection path syntax:
- Dot-delimited paths (for example `documents.pages.image_base64`).
- `*` matches one path segment.
- Invalid projection paths return `error.code = projection.path_invalid`.

Rollout semantics:
- Newly published workflow versions use no-inline defaults (`state_exclude_paths` preconfigured for document binary fields).
- Existing published versions keep legacy behavior unless explicitly switched.

Agent default behavior:
- Document metadata-first context is preferred by default.
- Full content should be fetched explicitly via artifact read operation (for example `read_artifact(ref)`).

Artifact read endpoint:
- `GET /artifacts/{artifact_ref}` returns explicit artifact payload.
- Error codes:
  - `artifact.not_found`
  - `artifact.access_denied`
  - `artifact.expired`

## Capability registry and version pinning
- Register versioned capability contracts:
  - `POST /capabilities`
- List capability versions:
  - `GET /capabilities?capability_id=...`
  - `GET /capabilities/{capability_id}/versions`
- Registry note:
  - `/capabilities*` is reserved for versioned capability contract registration/listing.
  - Client feature negotiation is exposed separately via `GET /integration-capabilities`.

Capability contract supports:
- `inputs`
- `outputs`
- `constraints`
- `timeout_s`
- `retry_policy`
- `error_codes`

Workflow nodes can pin capability version through `node.config`:
- `capability_id`
- `capability_version`

Runtime validates pinned references when present.

## Integration capability negotiation
- Endpoint: `GET /integration-capabilities` (public, read-only, no auth).
- Purpose: machine-readable external-client negotiation contract for:
  - typed error schema/version/categories
  - auth/header expectations
  - canonical chat endpoint + deprecated alias lifecycle
  - runtime feature flags (`projection_controls`, `document_payload`, capability registry, version pinning)
- Exclusions by design:
  - no tenant readiness checks
  - no onboarding doctor verdicts
  - no partner host policy or secret-expiry metadata

## Projects API
- List projects: `GET /projects`
  - Query params:
    - `limit` (optional, default `50`, max `200`)
    - `cursor` (optional, reserved for future pagination)
  - Response: `200` with `items[]` (`Project`) and `next_cursor` (`null` for current implementation).
- Create project: `POST /projects`
- Request body:
  - `project_id` (required)
  - `project_name` (required, human-readable display name)
  - `default_orchestrator_id` (optional)
  - `settings` (optional object, default `{}`)
    - `default_chat_workflow_id` (optional string; workflow used by project-scoped `POST /chat` thread creation)
- Response: `201` with `project_id`, `project_name`, `tenant_id`, `default_orchestrator_id`, `settings`, timestamps.
- Conflict behavior: if `project_id` already exists in the same tenant, API returns `409` with `error.code = CONFLICT`.
- Update project: `PATCH /projects/{project_id}`
  - Partial update.
  - Request body:
    - `project_name` (optional)
    - `settings` (optional object)
      - `default_chat_workflow_id` (optional string or `null`)
  - Supply at least one of `project_name` or `settings`.

## Project registry bootstrap endpoints
Public project-registry bootstrap no longer requires DB-side seeding.

- Upsert orchestrator config for project:
  - `POST /projects/{project_id}/orchestrators`
  - Request body:
    - `orchestrator_id` (required)
    - `name` (required)
    - `routing_policy` (optional object):
      - `confidence_threshold`
      - `switch_margin`
      - `max_disambiguation_turns`
      - `top_k_candidates`
      - `sticky`
      - `allow_switch`
      - `explicit_switch_only`
      - `cooldown_seconds`
      - `hysteresis_margin`
    - `fallback_workflow_id` (optional)
    - `prompt_profile` (optional)
    - `set_as_default` (optional bool, default `false`)
  - Response: `201` with persisted orchestrator config.

- Upsert workflow definition in project routing index:
  - `POST /projects/{project_id}/workflow-definitions`
  - Request body:
    - `workflow_id` (required)
    - `name` (required)
    - `description` (required)
    - `tags` (optional string array)
    - `examples` (optional string array)
    - `active` (optional bool, default `true`)
    - `is_fallback` (optional bool, default `false`)
  - Response: `201` with persisted workflow definition.

Common validation/error behavior:
- `ERR_PROJECT_NOT_FOUND` when project is not registered in orchestrator project registry.
- `ERR_WORKFLOW_NOT_IN_PROJECT` when referenced workflow is missing in workflow store for that project scope.

## Project orchestrator entrypoint (MVP)
- Unified chat entrypoint: `POST /orchestrator/messages`
- `project_id` is required in request body.
- Routing modes:
  - `workflow_id` present -> direct workflow mode.
  - `workflow_id` absent -> orchestrator mode (`orchestrator_id` or project default).
- Every inbound message creates one orchestration decision log.
- `POST /orchestrator/messages` response now includes `decision_trace` for routing transparency:
  - candidate workflows with `score` and `reason_codes`
  - selected action + selected workflow
  - explicit `selection_reason`
  - switch details (`switch_from_workflow_id`, `switch_to_workflow_id`, `switch_reason`) when switching happens
- Route/action error contract in orchestrator response:
  - `action_error` is present when router selected an action but execution is restricted/failed by policy.
  - structure: `PlatformError` fields (`code`, `message`, `category`, `retryable`, `retry_after_s`, `bad_fields`, `unsupported_feature`, `docs_ref`, `details`, `correlation_id`) plus required `action`.
- Session context prefill:
  - Runtime injects persisted `session` context into workflow inputs as `inputs.context` (when available).
- Custom action envelope on orchestrator entrypoint:
  - `message.type` is optional:
    - omitted or `threads.add_user_message` -> standard text routing
    - `threads.custom_action` -> `message.text` is treated as `action_type`
  - For `threads.custom_action`, normalized `message.payload` fields are materialized into workflow inputs:
    - `inputs.action_type = message.text`
    - payload fields -> flattened into `inputs.*`
  - Existing `message.id` + `message.text` behavior remains backward compatible.

Validation errors:
- `ERR_PROJECT_ID_REQUIRED`
- `ERR_PROJECT_NOT_FOUND`
- `ERR_ORCHESTRATOR_NOT_IN_PROJECT`
- `ERR_WORKFLOW_NOT_IN_PROJECT`

Session stack diagnostics:
- `GET /orchestrator/sessions/{session_id}/stack?project_id=...`

Session/thread context API:
- `POST /orchestrator/context/get` (`context.get`)
- `POST /orchestrator/context/set` (`context.set`)
- `POST /orchestrator/context/unset` (`context.unset`)
- Scopes: `session` and `thread`
- Validation errors for context API return HTTP `422`.

Offline routing replay/eval:
- `POST /orchestrator/eval/replay`
- Read-only evaluation mode (does not start/resume/cancel runs).
- Input: labeled `cases[]` with `message_text` and optional expectations (`expected_action`, `expected_workflow_id`).
- Output:
  - per-case predicted action/workflow + decision trace
  - action_error (when policy blocks a switch or fallback is unavailable)
  - aggregate accuracy metrics (`action_accuracy`, `workflow_accuracy`, `exact_match_rate`)

## Agent integration kit URL
- Markdown entrypoint: `/agent-integration-kit`
- Machine-readable bundle: `/agent-integration-kit.json`
- Canonical manifest is exposed as `integration_manifest` in the JSON bundle:
  - `api_base_url`
  - `chat_api_url` (canonical `POST /chat`)
  - `integration_capabilities_url` (`GET /integration-capabilities`)
  - `host_policy` (partner-specific canonical host policy)
  - `deprecated_chat_alias_url` + deprecation metadata for `POST /chatkit`
  - canonical OAuth `auth_profile` (`oauth_client_credentials`)
  - required/optional headers
  - project scope + default chat readiness (when inferable)
  - secret expiry/rotation warning metadata
- Generated URLs inside the kit should stay on the current public API host and obey `integration_manifest.host_policy`.
- For pinned policy, clients must use `host_policy.canonical_base_url` only.
- Workflow authoring guide: `/workflow-authoring-guide`
- Project list endpoint: `GET /projects`
- Project bootstrap endpoint: `POST /projects`
- Project orchestrator config endpoint: `POST /projects/{project_id}/orchestrators`
- Project workflow definition endpoint: `POST /projects/{project_id}/workflow-definitions`
- Orchestrator message endpoint: `POST /orchestrator/messages`
- Orchestrator replay/eval endpoint: `POST /orchestrator/eval/replay`
- Orchestrator stack diagnostics: `GET /orchestrator/sessions/{session_id}/stack?project_id=...`
- Integration test UI: `/agent-integration-test`
- Integration test JSON report (doctor-style): `/agent-integration-test.json`
- Detailed integration logs: `/agent-integration-logs`
- Draft validator: `POST /agent-integration-test/validate-draft`

Integration doctor check contract (`/agent-integration-test.json`):
- Each check includes:
  - `id`
  - `status` (`PASS` | `WARN` | `FAIL`)
  - `severity`
  - `code`
  - `title`
  - `message`
  - `observed`
  - `expected`
  - `remediation`
  - `docs_ref`
- Backward-compatible legacy fields are still present:
  - `description`
  - `ok`
  - `detail`
- Optional query:
  - `project_id=<project_id>` to run project-scoped readiness checks against a specific project.
  - `partner_id=<partner_id>` to evaluate partner-specific host policy compliance.

## Detailed integration logging for agent onboarding
Use `GET /agent-integration-logs` to quickly diagnose integration issues when an external agent calls integration-kit/test endpoints.
This endpoint is intended for external integrators, but requires bearer auth.

Supported query params:
- `limit` (default `100`, max `500`)
- `correlation_id`
- `trace_id`
- `event`

Each log entry includes:
- `log_id`, `timestamp`, `level`
- `event`, `detail`
- `http_method`, `path`, `status_code`
- context fields: `correlation_id`, `trace_id`, `tenant_id`, `client_ip`, `user_agent`
- `context` object with endpoint-specific diagnostic metadata (for example, draft node/edge counts, validation errors count, check summary)

Example:
```bash
curl -sS "https://api.hq21.tech/agent-integration-logs?correlation_id=corr_123&limit=50" \
  -H "Authorization: Bearer <access_token>"
```

## Core workflow lifecycle
1. `GET /projects` list available project scopes (or `POST /projects` to create one with `project_id` + `project_name`)
2. `POST /capabilities` register capability contracts/versions used by workflow nodes
3. `POST /workflows` create workflow draft
4. `PUT /workflows/{workflow_id}/draft` update draft
5. `POST /workflows/{workflow_id}/publish` publish immutable version
6. `POST /projects/{project_id}/workflow-definitions` register workflow in project routing index
7. `POST /projects/{project_id}/orchestrators` bind/set default orchestrator for project
8. `POST /orchestrator/messages` route project message (direct mode with `workflow_id` or orchestrated mode)
9. `POST /orchestrator/eval/replay` run offline routing replay/eval over labeled cases
10. `POST /workflows/{workflow_id}/runs` start run directly (non-chat/direct lifecycle)
11. `GET /runs/{run_id}` read state
12. `GET /runs/{run_id}/stream` consume SSE events
13. `GET /runs/{run_id}/ledger` read immutable execution ledger
14. `POST /runs/{run_id}/interrupts/{interrupt_id}/resume` continue after human input
15. `POST /runs/{run_id}/cancel` cancel run
16. `POST /runs/{run_id}/rerun-node` rerun node

## Atomic handoff API
- Create handoff package and start run atomically:
  - `POST /handoff/packages`
- Deterministic replay from stored package:
  - `POST /handoff/packages/{handoff_id}/replay`

Handoff package includes:
- `context`
- `constraints`
- `expected_result`
- `acceptance_checks`
- optional `replay_mode=deterministic`

Use `Idempotency-Key` on handoff endpoints for retry-safe delivery.

## Chat-first integration for external clients
For full user interaction (approval/forms/files) integrate `POST /chat` in addition to run APIs.
- Canonical public endpoint: `POST /chat`.
- Compatibility alias (deprecated): `POST /chatkit`.
  - During transition window, `/chatkit` returns the same payload/SSE behavior as `/chat`.
  - `/chatkit` responses include `Deprecation: true` and `Sunset: Sat, 04 Apr 2026 00:00:00 GMT`.
  - Starting `2026-04-04T00:00:00Z`, `/chatkit` returns `410 Gone`.

- Supported interactive request types:
  - `threads.create`
  - `threads.add_user_message`
  - `threads.custom_action`
- `threads.create` resolution order:
  - `metadata.workflow_id` -> explicit direct workflow mode (backward-compatible)
  - else `metadata.project_id` -> resolve `projects.settings.default_chat_workflow_id`
  - else `X-Project-Id` -> resolve `projects.settings.default_chat_workflow_id`
  - else return `CHAT_PROJECT_SCOPE_REQUIRED`
- Project-scoped thread creation requires a configured published default workflow:
  - missing project setting -> `CHAT_DEFAULT_WORKFLOW_NOT_CONFIGURED`
  - configured workflow missing/inactive/unpublished -> `CHAT_DEFAULT_WORKFLOW_NOT_FOUND`
- For `threads.custom_action`:
  - Preferred canonical field: `action.action_type`
  - Backward-compatible alias field: `action.type`
  - Runtime resolves aliases to canonical action type before execution/idempotency.
  - For `interrupt.submit`, runtime normalizes payload natively:
    - source priority: `payload.input` -> `payload.form` -> `payload.form_data` -> `payload.fields` -> fallback top-level keys
    - nested wrapper keys are flattened into a single input object
    - scalar strings are typed when safe (`true/false`, numeric literals, `null`)
    - `documents` payload passes through unchanged
    - `state_exclude_paths` / `output_include_paths` are validated using run projection path rules
- Backward compatibility:
  - Existing clients that pass `metadata.workflow_id` (and optional `metadata.workflow_version_id`) continue unchanged.
- Recommended metadata keys for reconciliation:
  - `external_user_id`
  - `external_session_id`
- Persist and reconcile:
  - `thread_id` (chat session identity)
  - `run_id` (workflow execution identity)
  - `interrupt_id` (human-interaction step identity)
  - resolved `project_id`
  - resolved `workflow_id`
  - `chat_resolution_mode` (`explicit_workflow`, `project_default`, `header_default`)

`POST /chat` uses the same OAuth access token model as other protected API endpoints.

## Example: start chat thread from project scope only (SSE)
```bash
curl -N -X POST "https://api.workcore.build/chat" \
  -H "X-Project-Id: proj_chat" \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {
      "project_id": "proj_chat",
      "external_user_id": "u_77",
      "external_session_id": "sess_123"
    },
    "type": "threads.create",
    "params": {
      "input": {
        "content": [{"type": "input_text", "text": "start"}],
        "attachments": [],
        "inference_options": {}
      }
    }
  }'
```

## Example: explicit workflow override remains valid
```bash
curl -N -X POST "https://api.workcore.build/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {
      "workflow_id": "wf_chat",
      "workflow_version_id": "v1",
      "project_id": "proj_chat"
    },
    "type": "threads.create",
    "params": {
      "input": {
        "content": [{"type": "input_text", "text": "start"}],
        "attachments": [],
        "inference_options": {}
      }
    }
  }'
```

## Example: submit interrupt action from chat widget
```bash
curl -N -X POST "https://api.workcore.build/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "threads.custom_action",
    "params": {
      "thread_id": "thr_01",
      "action": {
        "action_type": "interrupt.approve",
        "payload": {
          "run_id": "run_01",
          "interrupt_id": "intr_01",
          "idempotency_key": "approve_intr_01_v1"
        }
      }
    }
  }'
```

Fallback recommendations:
- Use `GET /runs/{run_id}/stream` with `Last-Event-ID` for reconnect.
- Subscribe to outbound webhooks (`interrupt_created`, `run_completed`, `run_failed`, `node_failed`) for delayed/offline processing.

## Example: create + publish + run
```bash
curl -sS -X POST "https://api.workcore.build/workflows" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: tenant_a" \
  -H "X-Correlation-Id: corr_create_1" \
  -H "X-Trace-Id: trace_create_1" \
  -d '{
    "name": "document_import_v1",
    "draft": {
      "nodes": [{"id":"start","type":"start"},{"id":"end","type":"end"}],
      "edges": [{"source":"start","target":"end"}],
      "variables_schema": {}
    }
  }'
```

```bash
curl -sS -X POST "https://api.workcore.build/workflows/<workflow_id>/publish" \
  -H "X-Tenant-Id: tenant_a" \
  -H "X-Correlation-Id: corr_publish_1" \
  -H "X-Trace-Id: trace_publish_1"
```

```bash
curl -sS -X POST "https://api.workcore.build/workflows/<workflow_id>/runs" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: tenant_a" \
  -H "X-Project-Id: project_42" \
  -H "X-Import-Run-Id: import_9001" \
  -H "X-Correlation-Id: corr_run_1" \
  -H "X-Trace-Id: trace_run_1" \
  -H "Idempotency-Key: run_start_001" \
  -d '{
    "inputs": {
      "source":"upload",
      "documents":[
        {
          "doc_id":"doc_1",
          "filename":"claim-photo.jpg",
          "type":"image",
          "pages":[
            {
              "page_number":1,
              "mime_type":"image/jpeg",
              "artifact_ref":"artf_tenant_a_01"
            }
          ]
        }
      ]
    },
    "state_exclude_paths":["documents","documents.pages.image_base64"],
    "output_include_paths":["result.claim_id","result.decision"],
    "metadata": {"user_id":"u_77"},
    "mode": "async"
  }'
```

## Example: stream run events (SSE)
```bash
curl -N "https://api.workcore.build/runs/<run_id>/stream" \
  -H "X-Tenant-Id: tenant_a" \
  -H "Last-Event-ID: evt_123"
```

Event payload includes `sequence`, `correlation_id`, `trace_id`, `tenant_id`, `project_id`, `import_run_id`.

## Example: resume interrupt
```bash
curl -sS -X POST "https://api.workcore.build/runs/<run_id>/interrupts/<interrupt_id>/resume" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: tenant_a" \
  -H "X-Correlation-Id: corr_resume_1" \
  -H "X-Trace-Id: trace_resume_1" \
  -H "Idempotency-Key: intr_resume_001" \
  -d '{
    "input": {"approved": true}
  }'
```

## Tenant isolation rules
- Every request is evaluated in tenant scope (`X-Tenant-Id`, default `local`).
- Cross-tenant read/write attempts return `NOT_FOUND`.
- Idempotency keys are scoped by `(tenant_id, scope, idempotency_key)`.

## SDK
- Python SDK for HQ21 integration:
  - module: `apps/orchestrator/integration/hq21_client.py`
  - class: `WorkCoreClient`

Use OpenAPI-driven clients for frontend/backend where possible and keep versions aligned with API semver.
