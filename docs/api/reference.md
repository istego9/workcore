# WorkCore API Reference (v1)

This guide explains how to use the WorkCore API as an orchestration layer for HQ21.

Primary contract source: `/openapi.yaml` (OpenAPI 3.0.3).

## Base URL
- Local (Docker + local domain): `https://api.workcore.build`
- Local (direct service): `http://127.0.0.1:8000`
- Production: use your deployed API URL.

## Authentication
- WorkCore runtime profile requires `WORKCORE_API_AUTH_TOKEN`; send:
  - `Authorization: Bearer <token>`
- No bearer token is required for:
  - `GET /health`
  - `GET /openapi.yaml`
  - `GET /api-reference`
  - `GET /workflow-authoring-guide`
  - `GET /agent-integration-kit`
  - `GET /agent-integration-kit.json`
  - `GET /agent-integration-test`
  - `GET /agent-integration-test.json`
  - `GET /agent-integration-logs`
  - `POST /agent-integration-test/validate-draft`
  - `POST /webhooks/inbound/{integration_key}` (signature-based)

Inbound webhooks require signature headers generated with `WEBHOOK_DEFAULT_INBOUND_SECRET`:
- `X-Webhook-Timestamp`
- `X-Webhook-Signature`

ChatKit service auth is configured independently:
- If `CHATKIT_AUTH_TOKEN` is set on ChatKit, `POST /chatkit` requires the matching bearer token.

## Required integration headers
- `X-Tenant-Id`: tenant scope for all workflow/run operations.
- `X-Correlation-Id`: request correlation key; echoed in responses/errors.
- `X-Trace-Id`: distributed trace key; propagated to run metadata/events.
- `X-Project-Id`: required for all `/workflows*` authoring/read operations.
- `X-Project-Id` is not required for `POST /projects` (project is created from request body).

Optional headers:
- `X-Import-Run-Id`
- `X-User-Id`
- `Idempotency-Key` (recommended for mutating APIs)

## Error envelope
All API errors use:

```json
{
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "..."
  },
  "correlation_id": "corr_123"
}
```

## JSON schemas for workflow authoring
- Draft payload schema: `docs/api/schemas/workflow-draft.schema.json`
- Builder import/export schema (`workflow_export_v1`): `docs/api/schemas/workflow-export-v1.schema.json`
- Orchestrator strict routing schema: `docs/api/schemas/routing-decision.schema.json`

## Projects API
- Create project: `POST /projects`
- Request body:
  - `project_id` (required)
  - `default_orchestrator_id` (optional)
  - `settings` (optional object, default `{}`)
- Response: `201` with `project_id`, `tenant_id`, `default_orchestrator_id`, `settings`, timestamps.
- Conflict behavior: if `project_id` already exists, API returns `409` with `error.code = CONFLICT`.

## Project registry bootstrap endpoints
Public project-registry bootstrap no longer requires DB-side seeding.

- Upsert orchestrator config for project:
  - `POST /projects/{project_id}/orchestrators`
  - Request body:
    - `orchestrator_id` (required)
    - `name` (required)
    - `routing_policy` (optional object)
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

Validation errors:
- `ERR_PROJECT_ID_REQUIRED`
- `ERR_PROJECT_NOT_FOUND`
- `ERR_ORCHESTRATOR_NOT_IN_PROJECT`
- `ERR_WORKFLOW_NOT_IN_PROJECT`

Session stack diagnostics:
- `GET /orchestrator/sessions/{session_id}/stack?project_id=...`

## Agent integration kit URL
- Markdown entrypoint: `/agent-integration-kit`
- Machine-readable bundle: `/agent-integration-kit.json`
- Workflow authoring guide: `/workflow-authoring-guide`
- Project bootstrap endpoint: `POST /projects`
- Project orchestrator config endpoint: `POST /projects/{project_id}/orchestrators`
- Project workflow definition endpoint: `POST /projects/{project_id}/workflow-definitions`
- Orchestrator message endpoint: `POST /orchestrator/messages`
- Orchestrator stack diagnostics: `GET /orchestrator/sessions/{session_id}/stack?project_id=...`
- Integration test UI: `/agent-integration-test`
- Integration test JSON report: `/agent-integration-test.json`
- Detailed integration logs: `/agent-integration-logs`
- Draft validator: `POST /agent-integration-test/validate-draft`

## Detailed integration logging for agent onboarding
Use `GET /agent-integration-logs` to quickly diagnose integration issues when an external agent calls integration-kit/test endpoints.

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
curl -sS "https://api.workcore.build/agent-integration-logs?correlation_id=corr_123&limit=50"
```

## Core workflow lifecycle
1. `POST /projects` create project scope
2. `POST /workflows` create workflow draft
3. `PUT /workflows/{workflow_id}/draft` update draft
4. `POST /workflows/{workflow_id}/publish` publish immutable version
5. `POST /projects/{project_id}/workflow-definitions` register workflow in project routing index
6. `POST /projects/{project_id}/orchestrators` bind/set default orchestrator for project
7. `POST /orchestrator/messages` route project message (direct mode with `workflow_id` or orchestrated mode)
8. `POST /workflows/{workflow_id}/runs` start run directly (non-chat/direct lifecycle)
9. `GET /runs/{run_id}` read state
10. `GET /runs/{run_id}/stream` consume SSE events
11. `POST /runs/{run_id}/interrupts/{interrupt_id}/resume` continue after human input
12. `POST /runs/{run_id}/cancel` cancel run
13. `POST /runs/{run_id}/rerun-node` rerun node

## Chat-first integration for external clients
For full user interaction (approval/forms/files) integrate `POST /chatkit` in addition to run APIs.

- Supported interactive request types:
  - `threads.create`
  - `threads.add_user_message`
  - `threads.custom_action`
- For `threads.create` pass `metadata.workflow_id` (and optional `metadata.workflow_version_id`).
- Recommended metadata keys for reconciliation:
  - `external_user_id`
  - `external_session_id`
- Persist and reconcile:
  - `thread_id` (chat session identity)
  - `run_id` (workflow execution identity)
  - `interrupt_id` (human-interaction step identity)

If `CHATKIT_AUTH_TOKEN` is configured on the ChatKit service, include:
- `Authorization: Bearer <token>`

## Example: start chat thread and run (SSE)
```bash
curl -N -X POST "https://api.workcore.build/chatkit" \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {
      "workflow_id": "wf_chat",
      "workflow_version_id": "v1",
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

## Example: submit interrupt action from chat widget
```bash
curl -N -X POST "https://api.workcore.build/chatkit" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "threads.custom_action",
    "params": {
      "thread_id": "thr_01",
      "action": {
        "type": "interrupt.approve",
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
    "inputs": {"source":"upload"},
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
