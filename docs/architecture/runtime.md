# Runtime Execution Model (Phase 2)

Date: 2026-01-29
Status: Draft

## Overview
The orchestrator executes workflow runs against a pinned published version. A run advances by scheduling node_runs when their dependencies are satisfied.
Runtime state is persisted in Postgres (`runs`, `node_runs`, `interrupts`) so runs can be resumed after service restarts.

## Run lifecycle
Statuses:
- RUNNING
- WAITING_FOR_INPUT
- COMPLETED
- FAILED
- CANCELLED

Transitions:
- RUNNING -> WAITING_FOR_INPUT (interrupt created)
- WAITING_FOR_INPUT -> RUNNING (interrupt resumed)
- RUNNING -> COMPLETED (end reached or output committed)
- RUNNING -> FAILED (node failure after retries)
- RUNNING -> CANCELLED (explicit cancel)

## Node run lifecycle
Statuses:
- TO_DO
- IN_PROGRESS
- RESOLVED
- ERROR
- CANCELLED

Transitions:
- TO_DO -> IN_PROGRESS -> RESOLVED
- TO_DO -> IN_PROGRESS -> ERROR (after retries exhausted)
- TO_DO -> CANCELLED (run cancelled)

## Scheduling and dependencies
- A node becomes runnable when all inbound dependencies are resolved.
- If/Else activates exactly one branch; nodes in non-selected branches are skipped.
- While nodes manage loop iterations and re-evaluate the condition on each cycle.
- The scheduler can run multiple runnable nodes concurrently but must preserve per-run event ordering.
- While loops require a loop_back node id to avoid re-entering the loop from the initial edge.
 - On each loop iteration, body node_runs are reset so they can execute again.

## Idempotency
- Node execution must be idempotent for the same run_id, node_id, and attempt.
- All side effects must either be idempotent or protected by external idempotency keys.

## Retries
- Each node can define max_retries (immediate retries; no backoff in MVP).
- Retries create a new attempt for the same node_id (attempt counter increments).
- After max retries, the node transitions to ERROR and the run transitions to FAILED.
- Optional timeout_s can mark a node attempt as failed when execution exceeds the limit (best-effort).

## Interrupt handling
- Interaction and Approval nodes create an interrupt and transition the run to WAITING_FOR_INPUT.
- Resuming an interrupt validates inputs/files, updates state, and continues scheduling.
- Cancelling an interrupt fails the node and the run unless explicitly configured otherwise.

## Prompt templates
- Agent `instructions` and `user_input` support template expressions: `{{ ... }}`.
- Interaction `prompt` also supports templates.
- Expressions are evaluated against `inputs`, `state`, and `node_outputs` (CEL or SimpleEvaluator).
  Example: `Hello {{state['user']}} (order {{inputs['order_id']}})`.

## Rerun semantics
- node_only: re-run the specific node, overwrite its output, and continue with existing downstream state only if explicitly allowed by node config.
- downstream: reset all downstream nodes to TO_DO and recompute from the rerun node.

## Event emission
Every state transition emits an event to Kafka and is persisted to the events table:
- run_started, node_started, node_completed, node_failed, node_retry
- run_waiting_for_input, run_completed, run_failed
- message_generated (agent streaming)
- run_cancelled (user requested cancellation)
- snapshot, stream_end

## Determinism
- Given the same inputs, workflow version, and tool outputs, the run must be reproducible.
- Tool outputs and external calls should be recorded for auditability.
