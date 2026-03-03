# Streaming and SSE

Date: 2026-03-03  
Status: Active

## Goal
Provide stable run progress streaming for `/runs/{run_id}/stream` with reconnect support that survives process restarts in Azure profile.

## Event pipeline
- Runtime emits domain events (`run_started`, `node_completed`, `run_waiting_for_input`, `run_completed`, `run_failed`, etc.).
- `EventPublisher` wraps runtime events into `EventEnvelope` with:
  - `id`
  - `sequence` (strictly increasing per `run_id`)
  - `timestamp`
  - trace metadata (`correlation_id`, `trace_id`, `tenant_id`, `project_id`, `import_run_id`)
- `EventPublisher` appends envelopes into `EventStore`.
- `EventPublisher` then publishes envelopes to `EventBus` for live subscribers.
- Runtime events are also projected into immutable `run_ledger` entries for audit/RCA; ledger is complementary and not used as SSE replay source.

## Replay and snapshot semantics
- SSE accepts `Last-Event-ID`.
- Reconnect policy:
  - If `Last-Event-ID` is provided, replay starts after that event id.
  - If `Last-Event-ID` is absent, endpoint emits one `snapshot` event first, then replays events after snapshot `last_event_id`.
- Snapshot payload must use run projection rules:
  - `state_exclude_paths`
  - `output_include_paths`
- This prevents reconnect from re-emitting large inline document payloads by default.

## Event store backends
### `memory` backend
- Default for local development and tests.
- Volatile process-local storage.

### `postgres` backend
- Required for Azure deployment profile.
- Uses existing `events` table as durable store:
  - runtime events stored as `type != 'snapshot'`
  - snapshots stored as `type = 'snapshot'`
  - per-run ordering via `sequence` (`uq_events_run_sequence`)
- Replay query uses persisted sequence order, not in-memory order.
- Snapshot query reads latest snapshot row for the run.

## Event bus backends
### `memory` backend
- Default local pub/sub.

### `kafka` backend
- Optional async pub/sub for distributed consumers.
- Partition key must be `run_id`.

## Configuration (env)
- `STREAMING_BACKEND=memory|kafka` controls `EventBus`.
- `STREAMING_STORE_BACKEND=memory|postgres` controls `EventStore`.
- `KAFKA_BOOTSTRAP_SERVERS=localhost:9092`
- `KAFKA_TOPIC=workflow-events`
- `KAFKA_GROUP_ID=workflow-sse`

## Runtime wiring
- `OrchestratorService` / `MultiWorkflowRuntimeService` publish through one `EventPublisher`.
- Snapshot is updated after each execution cycle (`start_run`, `resume_interrupt`, `rerun_node`).
- Public SSE contract stays unchanged (`GET /runs/{run_id}/stream`, SSE envelope format unchanged).

## Compatibility
- Additive only:
  - new store backend selector env.
  - no OpenAPI changes.
  - no event payload schema breaking changes.

## Testing requirements
- Unit: event publishing and sequence assignment.
- Integration: replay with `Last-Event-ID`.
- Integration: reconnect after service restart with `STREAMING_STORE_BACKEND=postgres`.
