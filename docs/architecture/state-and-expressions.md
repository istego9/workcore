# State and Expressions (Phase 2)

Date: 2026-01-29
Status: Draft

## State model
- inputs: validated workflow inputs.
- state: mutable runtime state.
- node_outputs: map of node_id -> output.

## Expression context (CEL)
Expressions run with a fixed context:
- inputs
- state
- node_outputs

Note: The runtime uses a CEL-compatible evaluator. Test harnesses may use a minimal safe evaluator, but production should use a CEL library.

## CEL implementation
The production evaluator uses cel-python to compile expressions and evaluate them against the activation context (inputs, state, node_outputs). Use json_to_cel to convert Python data into CEL values before evaluation.

Example:
- state.intent == "refund"
- inputs.customer_text != ""
- node_outputs["n2"].score > 0.8

## Type validation
- Start node validates inputs against variables_schema.
- Set State validates assigned values against the declared schema.
- Schema errors are surfaced as INVALID_ARGUMENT.

## Output templating
- Output nodes can interpolate from state and node_outputs.
- Missing references are treated as INVALID_ARGUMENT.
