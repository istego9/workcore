# Streaming and SSE (Phase 4)

Date: 2026-01-29
Status: Draft

## Event pipeline
- Orchestrator emits runtime events (run_started, node_completed, etc.).
- EventPublisher wraps runtime events into EventEnvelope (event_id + timestamp).
- Events are persisted in EventStore and published to EventBus.
- The same runtime events are also projected into immutable `run_ledger` records for RCA/audit use cases.

## Replay and snapshot
- SSE endpoint accepts Last-Event-ID.
- Replay: EventStore returns events after the given ID.
- Snapshot: optional SnapshotProvider can emit a snapshot event before replay when Last-Event-ID is not provided.
- Snapshot payloads should honor run projection settings (`state_exclude_paths`, `output_include_paths`)
  so SSE reconnect does not re-expand large document payloads.

## SSE endpoint
- `/runs/{run_id}/stream`
- Content-Type: text/event-stream
- Event format: id + event + data (JSON payload)

## Kafka
- EventBus interface can be backed by Kafka with partitions keyed by run_id.
- In-memory bus is used for local tests.
- KafkaEventBus uses aiokafka for async publish/subscribe.

## Configuration (env)
- STREAMING_BACKEND=memory|kafka
- KAFKA_BOOTSTRAP_SERVERS=localhost:9092
- KAFKA_TOPIC=workflow-events
- KAFKA_GROUP_ID=workflow-sse

## Runtime wiring
- OrchestratorService publishes runtime events to EventPublisher.
- A snapshot event is stored after each run execution step for SSE initial state.

## Testing
- Tests are headless and use in-memory store/bus.
