---
name: workflow-authoring-quality-gates
description: Enforce publish-time quality gates for workflow authoring to reduce run failures from schema-contract mismatches, CEL expression defects, and missing resilience controls. Use when designing, reviewing, or hardening workflow versions.
---

# Workflow Authoring Quality Gates

## Goal
Reduce failed runs caused by authoring defects before they reach production.

## Use when
- New workflow versions are prepared for publish.
- RCA points to schema/CEL/branching defects.
- You need deterministic acceptance gates for workflow quality.

## Primary evidence sources
- `docs/exec-plans/completed/2026-03-04-workflow-run-failures-rca.md`
- `docs/architecture/runtime.md`
- `docs/architecture/node-semantics.md`
- `docs/api/schemas/workflow-draft.schema.json`

## Quality gates
1. Schema robustness.
- Required output fields match realistic model behavior.
- Strict constraints (for example `minItems`) have fallback handling.
- Missing-data path does not hard-fail the run by default.

2. Contract compatibility.
- Agent output type and keys match declared schema.
- No undocumented fields are required by downstream nodes.

3. CEL safety.
- Type-safe ternary/comparison/logical usage.
- Guard checks for missing keys before access.
- No ambiguous overload patterns.

4. Expression maintainability.
- Large expressions are decomposed into smaller, testable steps.
- Complex transformations are not concentrated in a single fragile node.

5. Resilience controls.
- Retry/timeout are intentionally configured for failure-prone nodes.
- External dependency nodes include bounded retry strategy.

6. Publish readiness.
- Version notes include risk assessment.
- Rollback path is clear (previous active version available).

## Workflow
1. Collect workflow context.
- workflow id/version id
- failed node history (if any)
- target environments

2. Run gate-by-gate assessment.
- Mark each gate as `PASS`, `WARN`, or `FAIL`.
- Attach concrete evidence (node id, expression, schema field).

3. Produce remediation items.
- Convert `FAIL` and `WARN` into explicit action items.
- Keep actions minimal and ordered by blast radius.

4. Validate with tests/smokes.
- Run relevant checks:
  - `./scripts/archctl_validate.sh`
  - `./.venv/bin/python -m pytest apps/orchestrator/tests`
  - targeted E2E if UI/runtime path is affected

5. Approve or block publish.
- Block on unresolved `FAIL`.
- Allow with noted residual risk only when explicitly approved.

## Output template
```md
# Workflow Quality Gate Report

## Target
- workflow:
- version:

## Gate results
- Schema robustness: PASS/WARN/FAIL
- Contract compatibility: PASS/WARN/FAIL
- CEL safety: PASS/WARN/FAIL
- Expression maintainability: PASS/WARN/FAIL
- Resilience controls: PASS/WARN/FAIL
- Publish readiness: PASS/WARN/FAIL

## Findings
- [P0/P1/P2] node_id: issue, evidence, impact

## Action items
1. ...

## Decision
- Publish: yes/no
- Conditions:
```

## Guardrails
- Do not fabricate runtime fields or node capabilities.
- Do not relax schema/CEL constraints without documenting compatibility impact.
- Never mark a gate passed without concrete evidence.
- If required data is missing, block and add explicit `TODO`.

## Done criteria
- All `FAIL` findings are resolved or formally accepted with owner and due date.
- Report includes evidence and rollback notes.
- Validation commands and actual outcomes are recorded.
