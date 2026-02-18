# State and Expressions (Phase 2)

Date: 2026-01-29
Status: Draft

## State model
- inputs: validated workflow inputs.
- state: mutable runtime state.
- node_outputs: map of node_id -> output.
- For document payloads, use artifact references (`artifact_ref`) as default content carrier.
- Projection controls (`state_exclude_paths`, `output_include_paths`) reduce persisted/returned payload size but do not change CEL context keys.

## Expression context (CEL)
Expressions run with a fixed context:
- inputs
- state
- node_outputs

Projection note:
- CEL evaluation runs against the active in-memory context.
- Persisted/snapshot representations may be projected (paths excluded/allowlisted) for transport efficiency.

Note: The runtime uses a CEL-compatible evaluator. Test harnesses may use a minimal safe evaluator, but production should use a CEL library.

## CEL implementation
The production evaluator uses cel-python to compile expressions and evaluate them against the activation context (inputs, state, node_outputs). Use json_to_cel to convert Python data into CEL values before evaluation.

Example:
- state.intent == "refund"
- inputs.customer_text != ""
- node_outputs["n2"].score > 0.8

## Type validation
- Start node validates inputs against variables_schema.
- Set State validates assigned values against the declared schema for both:
  - legacy single assignment (`target` + `expression`)
  - batch assignments (`assignments[]`)
- Schema errors are surfaced as INVALID_ARGUMENT.

## Output templating
- Output nodes can interpolate from state and node_outputs.
- Missing references are treated as INVALID_ARGUMENT.
