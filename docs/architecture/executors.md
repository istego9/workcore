# Executors (Phase 3)

Date: 2026-01-29
Status: Draft

## Agent executor
- Uses the OpenAI Agents SDK (Python) to run Agent nodes.
- Streaming is handled by `Runner.run_streamed` and `stream_events()`.
- Partial chat updates are emitted when `run_item_stream_event` contains `message_output_item`.
- Model resolution order: node config `model` -> `OPENAI_MODEL` env var -> `gpt-5.2`.
- Runtime selection precedence for live vs mock:
  - `run.metadata.agent_executor_mode` (`live` or `mock`)
  - `run.metadata.agent_mock` (boolean)
  - `run.metadata.llm_enabled` (boolean)
  - `run.mode` (`live` => live executor, `test` => mock executor) when metadata flags are not set
  - Service default executor configured by `AGENT_EXECUTOR_MODE`.
- API run `mode` is mapped to metadata hints:
  - `mode=live` => `agent_executor_mode=live`, `agent_mock=false`, `llm_enabled=true`
  - `mode=test` => `agent_executor_mode=mock`, `agent_mock=true`, `llm_enabled=false`
  - omitted `mode` keeps metadata unchanged; executor selection still falls back to `run.mode`.

## LLM provider configuration
- Default provider is OpenAI.
- Azure OpenAI is supported when `AZURE_OPENAI_ENDPOINT` is set.
- OpenAI credentials:
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
- Azure OpenAI credentials:
  - `AZURE_OPENAI_API_KEY`
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_API_VERSION`
  - `OPENAI_MODEL` should contain Azure deployment name.
- `OPENAI_API` controls Agents SDK request API mode:
  - `responses` (default)
  - `chat_completions`

## MCP executor
- Uses a self-hosted MCP client via `call_tool`.
- Enforces allowlist per node or workflow.
- Emits `tool_called` events for observability.
- If no MCP executor is wired into runtime, MCP nodes fail with `MCP executor not configured`.

## Output validation
- Structured outputs are validated with JSON Schema when `output_schema` is provided.
- When `output_schema` is present for JSON outputs, the schema is also passed to the model as
  structured output format (Agents SDK `output_type`) before runtime validation.
- JSON normalization/validation is enabled for `output_format` values:
  - `json`
  - `json_schema` (`json-schema`/`jsonschema` aliases)
  - empty `output_format` when `output_schema` is present (compatibility path).
- If an Agent node omits `user_input`, runtime provides a default JSON payload:
  `{ "input": <run.inputs>, "state": <run.state>, "node_outputs": <run.node_outputs> }`.
- For document inputs, metadata-first payloads are preferred by default:
  - `doc_id`, `filename`, `mime_type`, `page_count`, optional preview metadata.
  - full document/page bodies are fetched explicitly via artifact read operation (for example `read_artifact(ref)`), not automatically injected into prompts.
- After validation, runtime can propagate Agent output into run state:
  - `state_target` writes full output to explicit path.
  - Structured JSON output auto-merges top-level object keys into state unless
    `merge_output_to_state=false`.

## Dependencies
- `openai-agents`
- `openai`
- `jsonschema`

## Integration test (live)
Set either OpenAI or Azure OpenAI env vars and `OPENAI_MODEL`, then run:

`python3 -m unittest apps.orchestrator.tests.test_agent_executor_integration`

This test is skipped by default when env vars are not set.
