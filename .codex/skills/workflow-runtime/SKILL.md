---
name: workflow-runtime
description: Implement or modify the workflow orchestrator runtime: run lifecycle, node execution semantics, state, interrupts, retries, and persistence. Use when changing execution semantics, node statuses, state models, or adding node types.
---

# Workflow Runtime

## Key invariants
- Runs execute against a pinned published version (no drift).
- Node execution is idempotent (safe to retry after partial failure).
- Interrupts pause the run until resumed or cancelled.

## Steps
1) Define the execution model:
   - Graph traversal rules
   - Dependency resolution (when a node becomes runnable)
2) Implement run state and node_run state:
   - Statuses: TO_DO, IN_PROGRESS, RESOLVED, ERROR, CANCELLED
   - Timestamps, attempts, last_error
3) Implement runtime state:
   - Workflow input variables (design-time schema)
   - Per-run state
   - Previous node outputs referenced by reference_id
4) Implement interrupt handling:
   - Create interrupt and transition run to WAITING_FOR_INPUT
   - Resume: validate input/files, update state, continue execution
5) Add robust retry controls:
   - Per-node max retries
   - Exponential backoff
   - Timeout handling

## Definition of done
- Ensure deterministic, reproducible run behavior in tests.
- Cover start run -> interrupt -> resume -> completion in integration tests.
- Ensure recovery on crash/restart without orphaned runs/nodes.
