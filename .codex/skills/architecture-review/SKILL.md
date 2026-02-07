---
name: architecture-review
description: >
  Architecture review for module boundaries, dependency direction, persistence ownership,
  and event/API responsibilities. Use for subsystem changes, major refactors, and integration work.
---

# Architecture Review

## Goal
Catch boundary violations and risky coupling before merge.

## Read first
- `docs/architecture/overview.md`
- `docs/architecture/runtime.md`
- `docs/architecture/streaming.md`
- Relevant ADRs in `docs/adr/`

## Checklist
1) Ownership boundaries are clear (no hidden cross-module coupling).
2) Persisted data ownership remains explicit (no accidental shared mutable ownership).
3) Sync calls are justified; async/event paths are used where appropriate.
4) API and runtime semantics remain consistent with docs.
5) Correlation/trace propagation is preserved.

## Output format
- Findings ordered by severity: P0, P1, P2.
- For each finding: impact, evidence (file/line), recommendation.
- If no findings: state residual risks and test gaps.

## Guardrails
- Avoid introducing new frameworks for architecture-only changes.
- Prefer minimal changes that preserve existing contracts.
