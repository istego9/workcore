# Architecture Overview

Date: 2026-01-29
Status: Draft (Phase 0)

## Goals (MVP)
- Create workflows via a visual builder.
- Publish immutable workflow versions.
- Execute runs with state, retries, interrupts, and streaming progress.
- Interact with users via chat widgets/actions.
- Integrate via webhooks and MCP.

## System boundaries (logical)
- Builder UI: graph editor, validation, draft/publish UI, run view.
- Workflow Service: workflows, drafts, publish/rollback, versions.
- Capability Registry Service: versioned capability contracts and step-level capability pin validation.
- Orchestrator Service: project routing, intent orchestration, runs, node_runs, interrupts, execution semantics.
- Streaming Service: SSE over run events (snapshot + replay).
- Handoff Service: atomic workflow package intake and deterministic replay bootstrap.
- Webhooks Service: inbound triggers and outbound callbacks.
- ChatKit Server: advanced integration, sessions/threads, widgets/actions.
- Chat Frontend Shell: legacy ChatKit embed + optional forked chat UI (feature-flagged).
- MCP Bridge Service: internal authenticated HTTP bridge for MCP node execution.
- Integrations Layer: Agents SDK executor, MCP client, object storage.

## Core entities and IDs
- workflow_id, version_id, node_id
- run_id, node_run_id, interrupt_id
- project_id, orchestrator_id, session_id, decision_id
- event_id, correlation_id, tenant_id, user_id
- project_id uniqueness is tenant-scoped (`tenant_id + project_id`).

## Event taxonomy baseline
Required fields for all events:
- event_id, timestamp
- run_id, workflow_id, version_id
- type, payload
Optional fields:
- node_id, attempt, correlation_id, tenant_id

MVP event types:
- snapshot
- run_started
- node_started
- node_completed
- node_failed
- node_retry
- run_waiting_for_input
- run_completed
- run_failed
- message_generated
- stream_end

Ordering guarantees:
- Per-run ordering is preserved by partitioning the event bus by run_id.
- Cross-run ordering is not guaranteed.

## API boundary map (logical ownership)
- Workflow Service: /workflows, /workflows/{id}/draft, /workflows/{id}/publish, /workflows/{id}/rollback, /workflows/{id}/versions
- Orchestrator Service: /workflows/{id}/runs, /runs/{run_id}, /runs/{run_id}/cancel, /runs/{run_id}/rerun-node, /runs/{run_id}/interrupts/*
- Capability Registry Service: /capabilities, /capabilities/{capability_id}/versions
- Handoff Service: /handoff/packages, /handoff/packages/{handoff_id}/replay
- Project Router / Orchestrator entry: /orchestrator/messages, /orchestrator/sessions/{session_id}/stack
- Context API: /orchestrator/context/get, /orchestrator/context/set, /orchestrator/context/unset
- Streaming Service: /runs/{run_id}/stream (SSE)
- Webhooks Service: /webhooks/inbound/*, /webhooks/outbound/*
- ChatKit Server: chat sessions/threads, widget/actions endpoints
- Chat Frontend Shell: render chat timeline/composer/widgets over canonical `/chat` contract (`/chatkit` is a deprecated compatibility alias during transition window)
- MCP Bridge Service: internal `/internal/mcp/call` + `/health`

## Persistence and storage
- Postgres is the source of truth for workflow metadata, versions, runs, node_runs, interrupts, and delivery logs.
- Object storage holds user uploads and large node outputs; only references are stored in Postgres.
- Kafka is the event bus for run progress and streaming.
- ChatKit and orchestration persistence are tenant-scoped for strict multi-tenant isolation.

## Correlation and tracing
- correlation_id propagates from inbound requests to runs, node_runs, tool calls, and outbound webhooks.
- trace_id is linked to run_id and node_id for Agents SDK calls.

## Testing policy (headless)
- All automated browser/UI/E2E tests run headless in CI by default.
- Headed mode is allowed only for local debugging.
- No GUI dependencies are required to run CI test suites.

## Phase 2 docs
- Runtime execution model: docs/architecture/runtime.md
- Node semantics: docs/architecture/node-semantics.md
- State and expressions: docs/architecture/state-and-expressions.md
- Workflow authoring guide for agents: docs/architecture/workflow-authoring-agents.md

## Phase 3 docs
- Executors: docs/architecture/executors.md

## Phase 4 docs
- Streaming and SSE: docs/architecture/streaming.md

## Phase 5 docs
- Webhooks: docs/architecture/webhooks.md

## Phase 6 docs
- ChatKit server: docs/architecture/chatkit.md

## Operational docs
- Development workflow and merge gates: docs/DEV_WORKFLOW.md
- Agent autonomy harness: docs/architecture/agent-autonomy-harness.md
- Runbooks: docs/runbooks/README.md
- Postmortem template: docs/postmortems/template.md

## ADR index
- ADR-0001: Expression engine is CEL.
- ADR-0002: Use a self-hosted MCP client.
- ADR-0003: Kafka is the event bus.
- ADR-0004: Postgres + object storage for state and artifacts.
- ADR-0005: Headless testing is the default for UI/E2E.
- ADR-0006: Vite + Mantine for the builder UI.
- ADR-0007: Runtime run-state is persisted in Postgres.
- ADR-0009: Artifact-reference defaults and run projection rollout.
- ADR-0010: Frontend ChatKit fork boundary and compatibility strategy.
- ADR-0011: Internal MCP HTTP bridge for runtime MCP execution.
