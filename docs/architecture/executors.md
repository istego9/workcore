# Executors (Phase 3)

Date: 2026-01-29
Status: Draft

## Agent executor
- Uses the OpenAI Agents SDK (Python) to run Agent nodes.
- Streaming is handled by `Runner.run_streamed` and `stream_events()`.
- Partial chat updates are emitted when `run_item_stream_event` contains `message_output_item`.
- Model resolution order: node config `model` -> `OPENAI_MODEL` env var -> `gpt-5.2`.

## MCP executor
- Uses a self-hosted MCP client via `call_tool`.
- Enforces allowlist per node or workflow.
- Emits `tool_called` events for observability.

## Output validation
- Structured outputs are validated with JSON Schema when `output_schema` is provided.

## Dependencies
- `openai-agents`
- `openai`
- `jsonschema`

## Integration test (live)
Set `OPENAI_API_KEY` and `OPENAI_MODEL`, then run:\n
`python3 -m unittest apps.orchestrator.tests.test_agent_executor_integration`\n
This test is skipped by default when env vars are not set.
