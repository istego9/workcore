# Runtime Execution Model (Phase 2)

Date: 2026-01-29
Status: Draft

## Overview
The orchestrator executes workflow runs against a pinned published version. A run advances by scheduling node_runs when their dependencies are satisfied.
Runtime state is persisted in Postgres (`runs`, `node_runs`, `interrupts`) so runs can be resumed after service restarts.
For document-heavy workloads, runtime supports artifact-reference inputs and run-level payload projections to reduce stored/returned JSON size.

Project-level orchestration adds an intent-routing layer in front of workflow execution:
- inbound message with `project_id` enters project router
- mode is selected: direct workflow (`workflow_id` provided) or orchestrated
- orchestrator evaluates intent and policy, then issues workflow adapter action (start/resume/cancel)
- every inbound message produces one orchestration decision log
- orchestrator response includes `decision_trace` with candidate scores, selected workflow/action, and selection/switch reason
- session context (when present) is injected into workflow inputs as `inputs.context`

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

## Unified context API (thread/session)
- Runtime exposes context operations:
  - `context.get`
  - `context.set`
  - `context.unset`
- Supported scopes:
  - `session` (typically keyed by orchestrator `session_id`)
  - `thread` (typically keyed by ChatKit `thread_id`)
- Context values are tenant-scoped persisted key/value records.
- Orchestrator routing can prefill workflow inputs from `session` scope (`inputs.context`).

## Integration HTTP node (non-MCP)
- Node type: `integration_http`
- Purpose: call external HTTP APIs from workflow runtime without MCP indirection.
- Core behavior:
  - configurable method/url/headers/auth
  - timeout + retry policy
  - optional request body expression evaluated from runtime context
  - response mapped to node output and optionally to configured state targets
- Error behavior:
  - `fail_on_status=true` fails node on unexpected HTTP status (after retries)
  - `allowed_statuses` can override status acceptance

## Cancel and commit-point semantics
- Engine adapter exposes per-run state with `cancellable` and optional `commit_point_reached`.
- Orchestrator can cancel active run only when `cancellable=true`.
- If `cancellable=false`, orchestrator returns explicit `ERR_CANCEL_NOT_ALLOWED` behavior and keeps run active.
- Hard workflow switching sequence: `cancel(current)` -> `start(new)`.

## Workflow version pinning
- External callers do not specify workflow version in orchestration mode.
- On start, engine resolves and pins `resolved_version` in run state.
- Resume always uses the pinned `resolved_version`, even if a newer workflow version is published later.

## Capability registry pinning
- Workflow steps can optionally pin capability contract via:
  - `node.config.capability_id`
  - `node.config.capability_version`
- Runtime validates pinned capability reference against tenant-scoped capability registry.
- If capability pin is missing in registry, run start fails with explicit validation error.
- Capability bindings are attached to run metadata to make chosen capability/version visible in downstream observability.

## Document payload mode and projections
- Document page content should be provided via `documents[].pages[].artifact_ref` by default.
- Inline content fields (for example `image_base64`) remain compatibility paths for migration windows.
- Run-level projection controls:
  - `state_exclude_paths`: excludes configured paths from persisted/returned run state payloads.
  - `output_include_paths`: allowlists output paths returned in run payloads.
- Projection controls target persistence/transport payload size and do not change expression evaluation semantics for the active in-memory execution context.
- Default behavior changes must be rollout-gated to new workflow versions; previously published versions keep legacy behavior unless explicitly migrated.

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

## Run ledger (immutable trace)
- Runtime events are projected into append-only `run_ledger` records.
- Each ledger record includes:
  - `workflow_id`, `version_id`, `run_id`
  - `step_id` (when available)
  - chosen `capability_id` and `capability_version` (when step pin is configured)
  - normalized `status`, event type, payload
  - extracted artifact references and timestamp
- Ledger records are immutable and ordered by creation time for RCA/audit/replay diagnostics.

## Atomic handoff
- `POST /handoff/packages` receives a workflow package and starts run execution in one API operation.
- Handoff payload captures:
  - context
  - constraints
  - expected_result
  - acceptance_checks
- Optional `replay_mode=deterministic` allows replay from stored package while preserving workflow version pin and package payload.

## Determinism
- Given the same inputs, workflow version, and tool outputs, the run must be reproducible.
- Tool outputs and external calls should be recorded for auditability.

## Capability pinning
- Workflow nodes can optionally pin capability contract via:
  - `node.config.capability_id`
  - `node.config.capability_version`
- Runtime validates pinned capability references against tenant-scoped capability registry.
- If capability pin is missing in registry, publish/start fails with explicit validation error.
- Resolved capability bindings are attached to run metadata for observability.

## Run ledger (immutable trace)
- Runtime events are projected into append-only `run_ledger` records.
- Each ledger record includes workflow/run identity, optional step, chosen capability/version, event/status, payload, artifact refs, and timestamp.
- Ledger has no update/delete API surface; records are immutable by design.

## Atomic handoff
- `POST /handoff/packages` accepts a workflow package (context, constraints, expected result, acceptance checks) and starts run execution atomically.
- Handoff record persists replay mode and package metadata.
- `POST /handoff/packages/{handoff_id}/replay` starts deterministic replay only for packages created with `replay_mode=deterministic`.
