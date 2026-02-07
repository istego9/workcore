---
name: streaming-sse
description: Implement SSE streaming of run progress events with reconnect support, snapshots, and stable event schemas. Use when adding /runs/{run_id}/stream, event types, snapshots, or replay.
---

# Streaming SSE

## Event schema baseline
Each event must include:
- event_id, timestamp
- run_id, workflow_id, version_id
- type, payload
Optional: node_id, attempt, correlation_id.

## Steps
1) Define minimal event types:
   - snapshot, run_started, node_started, node_completed, node_failed
   - run_waiting_for_input, run_completed, run_failed, stream_end
2) Implement SSE endpoint:
   - Content-Type: text/event-stream
   - Heartbeat
   - Reconnect semantics (Last-Event-ID)
3) Decide replay policy:
   - Store recent events per run (recommended), or
   - Only live stream (acceptable for MVP, but document limitations)
4) Add tests:
   - Stream opens
   - Receives snapshot
   - Reconnect continues from last event

## Definition of done
- Ensure SSE works in local dev and CI integration tests.
- Ensure UI can render node progress from streamed events.
