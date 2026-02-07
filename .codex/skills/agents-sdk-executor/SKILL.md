---
name: agents-sdk-executor
description: Implement Agent node execution using the OpenAI Agents SDK: tools, structured outputs, streaming, traces, and error handling. Use when adding or changing Agent nodes or streaming partial outputs.
---

# Agents SDK Executor

## Responsibilities
- Build agent call inputs from node config, run state, and previous node outputs.
- Validate outputs, especially structured JSON outputs.
- Emit progress events (node_started, partial_output, node_completed, node_failed).
- Capture traces and correlate them with run_id and node_id.

## Steps
1) Implement an adapter module `agent_executor`:
   - Input: node_config, run_context
   - Output: normalized result + trace metadata
2) Support structured outputs:
   - If a schema is provided, validate and fail fast on mismatch
3) Support streaming:
   - Surface partial outputs as events without breaking deterministic orchestration
4) Implement tooling controls:
   - Define a tool allowlist per node (or workflow)
   - Record tool calls in logs/traces
5) Handle failure modes:
   - Timeouts
   - Tool failures
   - Schema validation failures
   - Transient OpenAI errors (retry policy)

## Definition of done
- Unit tests cover adapter mapping and validation.
- Integration test runs an Agent node and produces expected output plus a trace link/id.
- Streaming updates are visible to SSE consumers.
