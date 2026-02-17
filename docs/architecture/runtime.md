# Runtime Execution Model (Phase 2)

Date: 2026-01-29
Status: Draft

## Overview
The orchestrator executes workflow runs against a pinned published version. A run advances by scheduling node_runs when their dependencies are satisfied.
Runtime state is persisted in Postgres (`runs`, `node_runs`, `interrupts`) so runs can be resumed after service restarts.

Project-level orchestration adds an intent-routing layer in front of workflow execution:
- inbound message with `project_id` enters project router
- mode is selected: direct workflow (`workflow_id` provided) or orchestrated
- orchestrator evaluates intent and policy, then issues workflow adapter action (start/resume/cancel)
- every inbound message produces one orchestration decision log

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

Orchestrator mode evaluates intent on every user message, including when a run is active.

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

## Project router and orchestration policy (MVP)
- `project_id` is unique only within `tenant_id`; all project router lookups are tenant-scoped.
- `project_id` is required for orchestrated chat entry.
- `workflow_id` present => direct workflow mode.
- `workflow_id` absent => orchestrator mode (explicit `orchestrator_id` or project default).
- Candidate workflows are shortlisted from `workflow_definitions` by tags/examples and bounded by `top_k_candidates`.
- The LLM router returns a strict structured decision.

Anti-flapping policy with active run:
- STOP/OPERATOR intent has highest priority.
- SWITCH requires high confidence and `switch_margin` above configured threshold.
- Otherwise continue current run (`RESUME_CURRENT`).

Low-confidence handling:
- Ask one clarifying question (`DISAMBIGUATE`) and persist pending disambiguation state.
- Retry intent routing after user reply.
- Move to fallback after max disambiguation turns.

## Cancel and commit-point semantics
- Engine adapter exposes per-run state with `cancellable` and optional `commit_point_reached`.
- Orchestrator can cancel active run only when `cancellable=true`.
- If `cancellable=false`, orchestrator returns explicit `ERR_CANCEL_NOT_ALLOWED` behavior and keeps run active.
- Hard workflow switching sequence: `cancel(current)` -> `start(new)`.

## Workflow version pinning
- External callers do not specify workflow version in orchestration mode.
- On start, engine resolves and pins `resolved_version` in run state.
- Resume always uses the pinned `resolved_version`, even if a newer workflow version is published later.

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
