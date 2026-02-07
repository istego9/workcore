# WorkCore API Reference (v1)

This guide explains how to use the WorkCore API as an orchestration layer for HQ21.

Primary contract source: `/openapi.yaml` (OpenAPI 3.0.3).

## Base URL
- Local (Docker + local domain): `https://api.workcore.build`
- Local (direct service): `http://127.0.0.1:8000`
- Production: use your deployed API URL.

## Authentication
- If `WORKCORE_API_AUTH_TOKEN` is set, send:
  - `Authorization: Bearer <token>`
- No bearer token is required for:
  - `GET /health`
  - `GET /openapi.yaml`
  - `GET /api-reference`
  - `POST /webhooks/inbound/{integration_key}` (signature-based)

## Required integration headers
- `X-Tenant-Id`: tenant scope for all workflow/run operations.
- `X-Correlation-Id`: request correlation key; echoed in responses/errors.
- `X-Trace-Id`: distributed trace key; propagated to run metadata/events.

Optional headers:
- `X-Project-Id`
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

## Agent integration kit URL
- Markdown entrypoint: `/agent-integration-kit`
- Machine-readable bundle: `/agent-integration-kit.json`
- Workflow authoring guide: `/workflow-authoring-guide`
- Integration test UI: `/agent-integration-test`
- Integration test JSON report: `/agent-integration-test.json`
- Draft validator: `POST /agent-integration-test/validate-draft`

## Core workflow lifecycle
1. `POST /workflows` create workflow draft
2. `PUT /workflows/{workflow_id}/draft` update draft
3. `POST /workflows/{workflow_id}/publish` publish immutable version
4. `POST /workflows/{workflow_id}/runs` start run
5. `GET /runs/{run_id}` read state
6. `GET /runs/{run_id}/stream` consume SSE events
7. `POST /runs/{run_id}/interrupts/{interrupt_id}/resume` continue after human input
8. `POST /runs/{run_id}/cancel` cancel run
9. `POST /runs/{run_id}/rerun-node` rerun node

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
