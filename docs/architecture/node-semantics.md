# Node Semantics (Phase 2)

Date: 2026-01-29
Status: Draft

## Start
- Defines workflow input schema and default values.
- On run start: validate inputs, apply defaults, initialize state.

## If / Else
- Evaluate CEL expressions in order.
- First condition that evaluates true is selected; otherwise else branch.
- Only selected branch becomes active; non-selected branches are skipped.

## While
- Evaluate CEL condition before each iteration.
- Requires max_iterations; exceeding the limit fails the node and run.
- Each iteration must be able to mutate state to avoid infinite loops.
- Config requires body_target, exit_target, and loop_back (node id that returns to the while node).

## Set State
- Supports two config styles:
  - legacy single assignment: `target` + `expression`
  - batch assignments: `assignments[]` with `{ target, expression }`
- Runtime applies assignments in order; each next expression sees state updates from prior assignments.
- Result type must match the variable schema.

## Interaction
- Creates an interrupt with prompt and optional input schema.
- Run transitions to WAITING_FOR_INPUT until resumed.
- On resume, input is stored in state and the node resolves.
- Optional state_target stores the interrupt input into the given state path.

## Approval
- Specialized Interaction returning { approved: boolean, metadata }.

## Agent
- Executed via OpenAI Agents SDK.
- Supports tools, structured outputs, and streaming partial results.
- Output is always persisted to `node_runs.output` and `node_outputs[node_id]`.
- For document workflows, agent defaults should receive metadata-first document context; full page/body content is fetched explicitly from artifact references when needed.
- State propagation rules:
  - If `state_target` is configured, full node output is written to that state path.
  - If `state_target` is not set and node uses structured JSON output
    (`output_format=json|json_schema` or `output_schema` without format), top-level
    object fields are merged into state by default.
  - Set `merge_output_to_state=false` to disable default merge behavior.
- Emit message_generated events during streaming.

## MCP
- Executed via self-hosted MCP client.
- Default transport is internal MCP bridge (`POST /internal/mcp/call`).
- If bridge is not configured, node fails with explicit configuration error.
- Tool allowlist and auth via secrets manager.
- Output is normalized to JSON and stored in node_runs.output.
- Capability pin defaults:
  - missing config fields may be filled from `contract.constraints.mcp_defaults`
    (or compatibility key `contract.data_source_defaults.mcp`).
  - explicit node config always wins.
  - inline secret defaults are not allowed; only env refs (`*_env`) are allowed.

## Integration HTTP
- Executes direct HTTP request from runtime (non-MCP).
- Supports config for URL/method/headers/auth, timeout, and retries.
- Optional request body can be produced from expression context (`inputs`, `state`, `node_outputs`).
- Response envelope is stored in `node_runs.output` / `node_outputs[node_id]`.
- Optional config paths can write response envelope/body into run state.
- Capability pin defaults:
  - missing config fields may be filled from `contract.constraints.integration_http_defaults`
    (or compatibility key `contract.data_source_defaults.integration_http`).
  - explicit node config always wins.
  - inline secret defaults are not allowed; only env refs (`*_env`) are allowed.

## Output
- Produces final run output (text or JSON).
- Output can reference state and previous node outputs.

## End
- Marks the run as COMPLETED when reached.
