# API Conventions (Phase 1)

Date: 2026-01-29
Status: Draft

## Error envelope
All errors return the standard envelope:

```json
{
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "...",
    "details": {}
  },
  "correlation_id": "corr_123"
}
```

Common error codes:
- INVALID_ARGUMENT
- NOT_FOUND
- CONFLICT
- UNAUTHORIZED
- FORBIDDEN
- RATE_LIMITED
- PRECONDITION_FAILED
- INTERNAL

## Success correlation
- Successful JSON responses include `correlation_id` at the top level.
- `correlation_id` is accepted via `X-Correlation-Id` and generated when absent.
- `trace_id` is accepted via `X-Trace-Id` and propagated in run metadata/events.

## Tenant scope and auth
- Tenant scope is resolved from `X-Tenant-Id` (`local` fallback) and enforced on workflow/run reads and writes.
- Cross-tenant reads return `NOT_FOUND` to avoid data leakage.
- If `WORKCORE_API_AUTH_TOKEN` is configured, API endpoints require `Authorization: Bearer <token>`.
- `/health` and signed inbound webhooks (`/webhooks/inbound/{integration_key}`) are intentionally excluded from bearer-token enforcement.

## Run metadata transparency
- `POST /workflows/{workflow_id}/runs` accepts integration metadata:
  - `tenant_id`
  - `project_id`
  - `import_run_id`
  - `trace_id`
  - optional `correlation_id`, `user_id`
- Run responses mirror these fields under `metadata` and as top-level convenience fields.
- SSE event payloads include `sequence`, `correlation_id`, `trace_id`, and tenant/project/import identifiers.

## Idempotency
- Use `Idempotency-Key` for non-safe operations (run start/cancel/rerun, interrupt resume, inbound webhooks, chat actions).
- The same key within TTL returns the original response.
- Keys are scoped by `(tenant_id, idempotency_key, operation)`.

## Pagination
- List endpoints accept `limit` and `cursor`.
- Responses return `items` and `next_cursor`.
- If `next_cursor` is null, there are no more items.

## API reference endpoints
- `GET /openapi.yaml` returns the current OpenAPI contract.
- `GET /api-reference` returns an operator-focused quick reference.

## Time format
- All timestamps are ISO 8601 with timezone (RFC 3339).
