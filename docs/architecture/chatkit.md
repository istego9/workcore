# ChatKit Server (Phase 6)

Date: 2026-01-29
Status: Draft

## Scope
- Advanced integration server for ChatKit (self-hosted).
- Thread/session storage, message streaming, widgets/actions for interrupts.
- Mapping between ChatKit threads and workflow runs.

## Endpoints
- `POST /chatkit` — ChatKit Server endpoint (streaming + non-streaming requests).

## Thread ↔ Run mapping
- `thread.metadata.run_id` stores the active run.
- `thread.metadata.last_event_id` tracks last streamed run event to avoid replay.
- `thread.metadata.workflow_id` is stored for visibility.
- `metadata.workflow_id` is required on `threads.create` to select which published workflow to run.

## Message handling
- New user message:
  - If thread has an active run waiting for input, the message resumes the open interrupt.
  - Otherwise, the message starts a new run.
- Input extraction:
  - JSON object payloads are parsed into inputs when possible.
  - Otherwise, the text is stored under `message`.

## Interrupts → Widgets
- `approval` interrupts render an approve/reject widget.
- `interaction` interrupts render a form widget with a submit action.
- File upload guidance is provided inline; attachments are passed to the runtime when resuming.

## Widget templates
- Widget definitions live in `apps/orchestrator/chatkit/templates/*.widget`.
- Runtime uses `WidgetTemplate.from_file(...)` to build dynamic widgets.
- Edit templates with ChatKit Studio or by hand (JSON + Jinja data fields).

## Action types
- `interrupt.approve`
- `interrupt.reject`
- `interrupt.submit`
- `interrupt.cancel` (not supported in MVP; returns an error)

## Streaming behavior
- Run events are mapped to ChatKit stream events:
  - `run_started`, `node_started`, `node_completed`, `node_failed`, `node_retry` → progress updates.
  - `message_generated` → assistant message chunks (coalesced).
  - `run_waiting_for_input` → widgets.
  - `run_completed` / `run_failed` → assistant summary message.

## Storage (MVP)
- ChatKit data persists in Postgres tables: `chatkit_threads`, `chatkit_items`, `chatkit_attachments`.
- Attachments are stored in object storage (MinIO/S3-compatible); metadata tracks `object_key`.
- In-memory stores remain available for tests/dev.

## Service deployment
- Run ChatKit as a separate service using `apps/orchestrator/chatkit/service.py` (ASGI app).
- Health check: `GET /health`.
- ChatKit endpoint: `POST /chatkit`.
- Example: `uvicorn apps.orchestrator.chatkit.service:app --port 8001`
- Apply migrations with `python scripts/migrate.py` (uses `CHATKIT_DATABASE_URL` or `DATABASE_URL`).

## Auth (minimal guard)
- If `CHATKIT_AUTH_TOKEN` is set, `/chatkit` requires `Authorization: Bearer <token>`.

## Idempotency (actions)
- Actions are deduped via `idempotency_keys` (scope `chatkit_action`).
- Default key: `{run_id}:{interrupt_id}:{action_type}` unless the payload includes `idempotency_key`.
- TTL configurable via `CHATKIT_IDEMPOTENCY_TTL_SECONDS`.

## Next steps
- Add action idempotency and richer widget schemas.
- Wire multi-tenant auth and RBAC controls.

## Local E2E
- Use `scripts/chatkit_e2e.py` against a running ChatKit service.
- Provide a workflow selection via request metadata (script reads `CHATKIT_WORKFLOW_ID` and optional `CHATKIT_WORKFLOW_VERSION_ID`).
- If you don't have a builder yet, create + publish a workflow via the API or run `scripts/workflow_bootstrap.py`.
- One-step start: `scripts/chatkit_up.sh`
