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
- Evaluate expression and assign to target path.
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
- Output is persisted to node_runs.output and optionally merged into state.
- Emit message_generated events during streaming.

## MCP
- Executed via self-hosted MCP client.
- Tool allowlist and auth via secrets manager.
- Output is normalized to JSON and stored in node_runs.output.

## Output
- Produces final run output (text or JSON).
- Output can reference state and previous node outputs.

## End
- Marks the run as COMPLETED when reached.
