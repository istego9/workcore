# ADR-0009: Artifact-Reference Defaults and Run Projection Rollout

Date: 2026-02-18
Status: Proposed

## Context
Document workflows currently risk oversized payloads because binary-heavy fields can be duplicated across:
- run inputs,
- mutable run state,
- run outputs,
- snapshot/webhook transport payloads.

This increases transport size and downstream token usage when large payloads are passed into agent prompts.

## Decision
Adopt a phased, additive rollout for artifact-reference-first document handling and run projections:

1. Additive contract phase:
- Keep existing inline document payload compatibility.
- Add run-level projection controls:
  - `state_exclude_paths`
  - `output_include_paths`
- Treat `documents[].pages[].artifact_ref` as preferred content carrier for new integrations.

2. Runtime transport phase:
- Apply projection controls to API run payloads, SSE snapshots, and outbound webhook outputs.
- Keep execution semantics stable: CEL context remains `inputs`, `state`, `node_outputs`.

3. Agent default-input phase:
- When agent `user_input` is omitted, generate metadata-first document context by default.
- Full page/body content must be fetched explicitly via artifact-read operation.

4. Default-mode rollout phase:
- Enable no-inline-by-default behavior for newly published workflow versions in a controlled rollout window.
- Preserve legacy inline compatibility for existing published versions until explicitly migrated.

## Compatibility strategy
- Additive first, no immediate breaking removals.
- Existing inline payload producers remain functional during migration.
- Projection controls are optional and no-op when omitted.

## Consequences
- Lower transport payload size for run APIs and stream/webhook channels.
- Lower default prompt token pressure for agent nodes in document-heavy scenarios.
- Existing clients keep working while migration is staged.

## Risks and mitigations
- Risk: over-aggressive projection can hide fields needed by downstream consumers.
  - Mitigation: keep projections opt-in; validate path syntax; monitor response-size deltas and consumer errors.
- Risk: legacy flows still sending inline payloads retain high cost.
  - Mitigation: provide clear migration guidance toward `artifact_ref` payloads.

## Follow-up
- Finalize default rollout gate for new workflow versions.
- Finalize artifact lifecycle policy (retention/TTL/access errors) in API/runtime docs.
- Add observability dashboards for payload-size and token-efficiency metrics.

