# Data Sources In Nodes - Spec-First Action Items

Date: 2026-02-26
Status: IN_PROGRESS
Task classification: A (internal MCP bridge module), E (integration behavior), G (gap-closure bugfix/parity)

## 1) Goal and scope
- Close runtime and builder gaps for data source nodes:
  - wire `mcp` executor in API/ChatKit runtime,
  - expose/configure `integration_http` in Builder UI.
- Add internal MCP bridge HTTP boundary for runtime MCP calls.
- Apply additive capability defaults for `mcp` and `integration_http` with secret guardrails.

Out of scope:
- New public workflow endpoints.
- DB schema migrations.
- Breaking changes to workflow draft payloads.

## 2) Spec files to update (exact paths)
- `docs/architecture/runtime.md`
- `docs/architecture/executors.md`
- `docs/architecture/node-semantics.md`
- `docs/architecture/overview.md`
- `docs/adr/ADR-0011-internal-mcp-http-bridge.md`

## 3) Compatibility strategy (additive vs breaking)
- Additive only:
  - existing workflow payloads remain valid,
  - `mcp` failures become explicit config errors when bridge is missing,
  - non-`mcp` nodes keep existing behavior.

## 4) Implementation files
- Backend:
  - `apps/orchestrator/executors/mcp_executor.py`
  - `apps/orchestrator/executors/mcp_bridge_client.py` (new)
  - `apps/orchestrator/mcp_bridge/service.py` (new)
  - `apps/orchestrator/api/app.py`
  - `apps/orchestrator/chatkit/app.py`
  - `apps/orchestrator/chatkit/service.py`
  - `apps/orchestrator/runtime/multi_service.py`
- Frontend:
  - `apps/builder/src/builder/types.ts`
  - `apps/builder/src/builder/graph.ts`
  - `apps/builder/src/App.tsx`
  - `apps/builder/src/builder/graph.test.ts`
- Ops/config:
  - `docker-compose.workcore.yml`
  - `.env.example`
  - `.env.docker.example`

## 5) Tests (unit/integration/contract/e2e)
- Orchestrator unit tests:
  - MCP executor call path and validation.
  - MCP bridge client + bridge service request/response behavior.
  - Capability defaults precedence for `mcp`/`integration_http`.
- API/runtime tests:
  - `mcp` node explicit error when bridge is unconfigured.
  - `mcp` node success with mocked bridge response.
- Builder tests:
  - `integration_http` node type accepted/imported and validated.
- Relevant checks:
  - `./scripts/archctl_validate.sh`
  - `./.venv/bin/python -m pytest apps/orchestrator/tests`
  - `cd apps/builder && npm run test:unit`

## 6) Observability/security impacts
- Emit tool-call metadata (`run_id`, `node_id`, `correlation_id`, `trace_id`) through bridge request context.
- Do not log secret fields (`token`, `password`, raw credentials).
- Enforce secret guardrail in capability defaults (allow only env refs).

## 7) Rollout/rollback notes
- Rollout:
  - deploy MCP bridge service and env config,
  - enable runtime MCP wiring,
  - deploy Builder with `integration_http` UI parity.
- Rollback:
  - disable bridge config and revert runtime image; no DB rollback.

## 8) Outstanding TODOs/questions
- None blocking for implementation in this iteration.
