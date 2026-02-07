# ADR-0002: Use a Self-Hosted MCP Client

Date: 2026-01-29
Status: Accepted

## Context
MCP tool execution is required for integrations. We can use a remote MCP tool or operate our own MCP client.

## Decision
Use a self-hosted MCP client as the default execution path.

## Consequences
- Full control over auth, allowlists, timeouts, and observability.
- Higher implementation and operational overhead.
- Remote MCP via provider tools may be added later as an optional path.

## Alternatives Considered
- Remote MCP via provider tools: faster start but less control and different data policies.
