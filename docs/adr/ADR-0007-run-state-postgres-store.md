# ADR-0007: Persist Runtime Run State in Postgres

Date: 2026-02-06
Status: Accepted

## Context
Runtime `Run` state (`runs`, `node_runs`, `interrupts`) was held in memory in the API/ChatKit processes. This caused state loss on restart and inconsistent behavior across services.

## Decision
Use Postgres as the source of truth for run runtime state:
- Persist each run snapshot into `runs`.
- Persist node execution state into `node_runs`.
- Persist interrupt lifecycle state into `interrupts`.
- Load run state from Postgres for read, resume, cancel, and rerun operations.

Schema additions (non-breaking):
- `runs.mode`, `runs.node_outputs`, `runs.branch_selection`, `runs.loop_state`, `runs.skipped_nodes`
- `node_runs.trace_id`, `node_runs.usage`
- `interrupts.state_target`

## Consequences
- Run state survives restarts and is shared between API, ChatKit, and webhook-triggered flows.
- API/ChatKit behavior becomes consistent in multi-process deployment.
- Requires migration `003_run_state_persistence.sql` before serving traffic that mutates runs.

## Alternatives Considered
- Keep in-memory store: rejected due to data loss and cross-process inconsistency.
- New dedicated runtime-state store: rejected to avoid adding infrastructure and contracts.
