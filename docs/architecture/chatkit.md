# ChatKit Server (Phase 6)

Date: 2026-01-29
Status: Draft

## Scope
- Advanced integration server for ChatKit (self-hosted).
- Thread/session storage, message streaming, widgets/actions for interrupts.
- Mapping between ChatKit threads and workflow runs.
- Forked frontend chat shell (optional) compatible with the same `/chat` contract.

## Endpoints
- `POST /chat` — canonical ChatKit endpoint (streaming + non-streaming requests).
- `POST /chatkit` — deprecated compatibility alias for one release window.
  - Alias responses include `Deprecation: true` and `Sunset: Sat, 04 Apr 2026 00:00:00 GMT`.
  - Starting `2026-04-04T00:00:00Z`, alias returns `410 Gone`.
- `X-Tenant-Id` is required on every ChatKit request.

## External client contract (supported request types)
- `threads.create`:
  - Starts a new thread and usually starts a new run from the first user message.
  - Resolution order is:
    - `metadata.workflow_id` -> explicit direct workflow mode
    - else `metadata.project_id` -> resolve project default chat workflow
    - else `X-Project-Id` -> resolve project default chat workflow
    - else reject with `CHAT_PROJECT_SCOPE_REQUIRED`
  - `metadata.workflow_id` remains backward-compatible for existing clients.
  - `metadata.workflow_version_id` is optional; when omitted explicit mode uses the active/latest published version.
  - Project default chat workflow is stored in `projects.settings.default_chat_workflow_id`.
  - Project resolution failures:
    - missing setting -> `CHAT_DEFAULT_WORKFLOW_NOT_CONFIGURED`
    - configured workflow missing/inactive/unpublished -> `CHAT_DEFAULT_WORKFLOW_NOT_FOUND`
- `threads.add_user_message`:
  - Appends a user message to an existing thread and continues run execution.
- `threads.custom_action`:
  - Sends widget actions (`interrupt.approve`, `interrupt.reject`, `interrupt.submit`, `interrupt.cancel`).
  - Canonical field is `action.action_type`; backward-compatible alias `action.type` is still accepted.
  - Runtime currently rejects `interrupt.cancel` with an explicit error event.
- `input.transcribe`:
  - Accepts `params.audio_base64` + `params.mime_type`.
  - Returns non-streaming JSON payload `{ "text": "<transcript>" }`.

## Thread ↔ Run mapping
- `thread.metadata.run_id` stores the active run.
- `thread.metadata.last_event_id` tracks last streamed run event to avoid replay.
- `thread.metadata.project_id`, `thread.metadata.workflow_id`, and `thread.metadata.workflow_version_id` store resolved scope.
- `thread.metadata.chat_resolution_mode` records how the workflow was selected:
  - `explicit_workflow`
  - `project_default`
  - `header_default`
- `thread.metadata.correlation_id` is persisted for request-to-run correlation.
- External integrators should also persist their own identifiers in metadata (for example `external_user_id`, `external_session_id`) for cross-system reconciliation.

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

## Fork frontend boundary (Variant D)
- Legacy mode:
  - Builder embeds `openai-chatkit` page (`chatkit.html`).
- Fork mode:
  - Builder embeds `chat-fork.html` React shell behind feature flag.
  - Shell keeps parity with existing widget/action semantics and `/chat` payloads.
  - Extension renderer adds:
    - chart mapping to Nivo adapters (`chart_type` registry):
      - `bar`, `line`, `pie`, `area-bump`, `bump`
      - `boxplot`, `bullet`, `calendar`, `chord`, `circle-packing`
      - `funnel`, `geo`, `heatmap`, `icicle`, `marimekko`
      - `network`, `parallel-coordinates`, `polar-bar`, `radar`, `radial-bar`
      - `sankey`, `scatterplot`, `stream`, `sunburst`, `swarmplot`
      - `tree`, `treemap`, `waffle`
    - `DataTable` extension component (read-only MVP),
    - safe fallback card for unknown widget component types.

## Action types
- Canonical action types:
  - `interrupt.approve`
  - `interrupt.reject`
  - `interrupt.submit`
  - `interrupt.cancel` (not supported in MVP; returns an error)
- Alias map (accepted and normalized to canonical):
  - `approve` -> `interrupt.approve`
  - `reject` -> `interrupt.reject`
  - `submit` -> `interrupt.submit`
  - `cancel` -> `interrupt.cancel`

Action payload fields consumed by runtime:
- `action_type` (preferred canonical action type)
- `run_id` (optional when thread metadata already has run_id)
- `interrupt_id` (optional if there is a single OPEN interrupt)
- `input` / `form` / `form_data` / `fields` (for submit data)
- `files` (uploaded file refs)
- `idempotency_key` or `action_id` (optional client-supplied dedupe key)
- Submit payload normalization (WorkCore-native):
  - extraction order: `input` -> `form` -> `form_data` -> `fields` -> fallback top-level keys
  - wrapper keys are flattened into one input map
  - scalar strings are coerced to native types where safe (`true/false`, integer, float, `null`)
  - `documents` payload is passed through as-is
  - `state_exclude_paths` and `output_include_paths` are validated with projection path rules

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
- All ChatKit reads/writes are tenant-scoped.
- Project chat defaults reuse `projects.settings.default_chat_workflow_id`; no separate ChatKit config table is required.

## Service deployment
- Run ChatKit as a separate service using `apps/orchestrator/chatkit/service.py` (ASGI app).
- Health check: `GET /health`.
- ChatKit canonical endpoint: `POST /chat`.
- ChatKit compatibility alias: `POST /chatkit` (deprecated lifecycle described above).
- Example: `uvicorn apps.orchestrator.chatkit.service:app --port 8001`
- Apply migrations with `python scripts/migrate.py` (uses `CHATKIT_DATABASE_URL` or `DATABASE_URL`).

## Auth
- Single bearer profile: `/orchestrator/*` and `/chat` accept the same bearer token.
- Split bearer profile: `/chat` requires `Authorization: Bearer <CHATKIT_AUTH_TOKEN>`.
- ChatKit runtime enforces tenant scope from `X-Tenant-Id` and must reject requests without tenant header.
- `X-Project-Id` is optional on `POST /chat` and participates only in `threads.create` workflow resolution.

## Idempotency (actions)
- Actions are deduped via `idempotency_keys` (scope `chatkit_action`).
- Default key: `{run_id}:{interrupt_id}:{canonical_action_type}` unless the payload includes `idempotency_key`.
- TTL configurable via `CHATKIT_IDEMPOTENCY_TTL_SECONDS`.
- Idempotency reservation starts after action payload validation succeeds, so invalid submit payloads do not lock retries.

## Delivery and fallback strategy for third-party clients
- Primary: consume ChatKit SSE response stream from `POST /chat`.
- Run-level fallback: subscribe to `GET /runs/{run_id}/stream` using `Last-Event-ID` for reconnect.
- Webhook fallback: subscribe to outbound webhook events (`interrupt_created`, `run_completed`, `run_failed`, `node_failed`) for offline or delayed consumer scenarios.
- Persist `thread_id`, `run_id`, and open `interrupt_id` in the external system so retries and reconnects stay idempotent.

## STT dictation flow (MVP)
- Frontend captures short audio snippets through browser `MediaRecorder`.
- Frontend sends `input.transcribe` to `POST /chat`.
- Backend validates mime/size guardrails and calls configured transcriber.
- Response text is inserted into composer draft; user confirms send manually.

## Next steps
- Expand widget extension schema for richer table interactions (sorting/filter/pagination) in Phase 2.
- Evaluate voice mode (beyond dictation) separately from MVP.
- Wire RBAC controls for tenant-aware ChatKit operations.

## Local E2E
- Use `scripts/chatkit_e2e.py` against a running ChatKit service.
- Provide either explicit workflow metadata (`CHATKIT_WORKFLOW_ID`, optional `CHATKIT_WORKFLOW_VERSION_ID`)
  or project scope (`CHATKIT_PROJECT_ID`) with a configured `projects.settings.default_chat_workflow_id`.
- If you don't have a builder yet, create + publish a workflow via the API or run `scripts/workflow_bootstrap.py`.
- One-step start: `scripts/chatkit_up.sh`
