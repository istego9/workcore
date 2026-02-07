---
name: platform-architecture
description: Define system boundaries, core domain model, event taxonomy, and ADRs for the workflow platform. Use when starting a new subsystem, changing cross-cutting concerns (events, persistence, versioning, streaming), or clarifying service boundaries/contracts.
---

# Platform Architecture

## Inputs
- Collect target use cases (builder, operator, integrator).
- Collect non-functional goals (latency, scale, tenancy, compliance).
- Confirm existing stack constraints (language, infra, DB).

## Steps
1) Map bounded contexts:
   - Workflow authoring (draft graph, validation)
   - Versioning (publish/rollback)
   - Execution (runs, node_runs, interrupts)
   - Streaming (SSE)
   - Chat integration (ChatKit server + actions)
   - External integrations (webhooks, MCP)
2) Define core entities and IDs:
   - workflow_id, version_id, node_id, run_id, node_run_id, interrupt_id
3) Define the event schema baseline:
   - event_id, timestamp, tenant_id, correlation_id, run_id, version_id, node_id, type, payload
4) Decide critical guarantees:
   - Idempotency boundaries
   - Retry semantics
   - Ordering expectations (per-run ordering is typical)
5) Write ADRs for decisions that impact many files.

## Outputs
- Create a concise architecture note in `docs/architecture/overview.md`.
- Create 1 to 3 ADRs in `docs/adr/`.
- Document event taxonomy: event types, required fields, correlation strategy.
- Provide an API boundary map: which service owns which endpoints.

## Definition of done
- Ensure the architecture doc exists and is referenced from a docs index or README.
- Ensure ADRs exist for irreversible decisions.
- Ensure the event schema is documented and implementable.
