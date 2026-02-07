---
name: mcp-integration
description: Integrate MCP tool execution into the platform (remote MCP via provider tools or direct MCP client), with auth and guardrails. Use when implementing MCP node execution or adding tool servers.
---

# MCP Integration

## Requirements
- Never store secrets in node config; use a secrets manager.
- Log tool calls with correlation IDs.
- Enforce timeouts and response size limits.

## Steps
1) Choose execution path:
   - Remote MCP via provider tool support, or
   - Direct MCP client managed by this platform
2) Implement MCP node executor:
   - Validate config (server/tool/args)
   - Call tool
   - Normalize output
3) Apply guardrails:
   - Allowlist servers/tools per tenant/workflow
   - Timeouts + retries
   - Payload size caps
4) Add integration tests using a local mock MCP server.

## Definition of done
- MCP node works reliably with clear error handling.
- Auth is secure and auditable.
- Limits prevent runaway data transfers.
