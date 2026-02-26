# ADR-0011: Internal MCP HTTP Bridge For Runtime Execution

Date: 2026-02-26
Status: Accepted

## Context
Runtime supports `mcp` workflow nodes, but API/ChatKit runtime wiring had no production MCP transport.  
We need a controlled execution path that:
- keeps existing workflow/node contracts additive,
- supports clear auth/guardrails,
- avoids embedding provider-specific MCP transport details into runtime engine code.

## Decision
Use an internal authenticated HTTP bridge as default MCP execution boundary.

Execution path:
- runtime (`MCPExecutor`) -> `MCPBridgeHttpClient` -> bridge endpoint `POST /internal/mcp/call`
- bridge validates request/auth and delegates to configured upstream MCP tool transport.

Runtime wiring behavior:
- API/ChatKit always wire `mcp` executor.
- If bridge is not configured (`MCP_BRIDGE_BASE_URL` missing), `mcp` node fails with explicit configuration error.
- Non-`mcp` nodes are unaffected.

## Consequences
- Positive:
  - deterministic integration boundary for MCP in one place,
  - centralized auth/validation/observability for MCP tool calls,
  - additive rollout/rollback via env config (no DB migration).
- Tradeoff:
  - extra internal service hop and operational component.

## Security notes
- Bridge access can require bearer auth token (`MCP_BRIDGE_AUTH_TOKEN`).
- Capability defaults may not carry inline secrets; only env references are allowed.
- Runtime and bridge logs include correlation metadata, but not secret payloads.

## Alternatives considered
- Direct provider MCP transport inside runtime:
  - less moving parts, but tighter coupling and weaker boundary control.
- Keep MCP executor unwired:
  - lower effort, but leaves production gap unresolved.
