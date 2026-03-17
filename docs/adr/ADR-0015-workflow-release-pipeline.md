# ADR-0015: Builder Release Pipeline as Composed Workflow Lifecycle

Date: 2026-03-13  
Status: Accepted

## Context
Operators already had the required primitives in WorkCore:
- draft validation in Builder;
- immutable publish/rollback and version listing;
- replay/eval routing simulation via `/orchestrator/eval/replay`;
- project-level default chat workflow binding;
- run history and run debug inspector.

These capabilities existed as disconnected actions across different surfaces.  
The product requirement is to turn lifecycle promotion into one coherent release path:
Validate → Simulate → Diff → Publish → Bind → Smoke → Observe.

## Decision
1. Implement an additive, dedicated Builder release pipeline surface, without introducing a new subsystem boundary.
2. Compose existing API/runtime contracts in Builder and keep any control-plane contract additions additive and backward compatible.
3. Keep publish semantics unchanged (immutable versions, rollback contract), but make publish action explicitly gate-aware in the new surface.
4. Use deterministic machine-readable diff summary against the current published version content.
5. Treat binding as an explicit stage:
   - project default chat workflow binding via existing project settings update;
   - routing definition upsert via existing project workflow-definition endpoint;
   - routing bind completion is confirmed by authoritative readback of the stored project workflow definition.
6. Implement smoke as a bounded manual test run initiated from Builder, then normalize result and deep-link to run debug.
7. Produce a deterministic release report artifact (client-side JSON export) with lifecycle timestamps, stage summaries, run IDs, and correlation IDs.
8. Emit structured release pipeline logs in Builder for operational traceability.

## Consequences
### Positive
- Operators can execute and audit lifecycle progression from one surface.
- Release gating is explicit and explainable.
- No contract churn for v1; backward compatibility is preserved.
- Release report export provides deterministic handoff evidence.

### Tradeoffs
- Smoke is bounded/manual rather than asynchronous pipeline automation.
- Release proof still depends on a live acceptance lane in CI; mocked UI-contract tests remain useful but are not treated as end-to-end evidence.

### Compatibility
- Additive UI/runtime composition only.
- Existing endpoints, persisted state, publish/rollback behavior, and SSE payload semantics remain unchanged.
