# Reliability Baseline

## Purpose
Define reliability expectations and verification rules for runtime, integrations, and UI paths.
This file tracks policy and ownership; detailed troubleshooting remains in runbooks.

## System of record
- Process gates: `docs/DEV_WORKFLOW.md`
- Runtime behavior: `docs/architecture/runtime.md`
- Streaming behavior: `docs/architecture/streaming.md`
- Operational runbooks: `docs/runbooks/`

## Reliability objectives (to be baseline-scored)
Track these objectives per critical flow and tighten over time:
- request/operation latency (for critical endpoints and node execution paths),
- error rate on critical journeys,
- delivery success for webhook and streaming paths,
- regression resistance (tests/evals that would fail before a bugfix and pass after).

When hard numeric thresholds are not yet approved, mark them `TBD` with an owner and due date.

## Release gates
For reliability-impacting changes:
1. Run relevant automated checks from `AGENTS.md` and `docs/DEV_WORKFLOW.md`.
2. Add or update tests for changed behavior (unit/integration/contract/E2E as applicable).
3. Document new failure modes and rollback steps.
4. Record residual risks in PR notes.

## Operational readiness checklist
- [ ] Health checks are still meaningful and reachable in local/CI environments.
- [ ] Critical paths have test coverage and deterministic fixtures where possible.
- [ ] Runbooks cover symptom -> diagnosis -> mitigation for affected components.
- [ ] Rollback path is explicit for behavior that can affect run execution or delivery.

## Runbook index
- `docs/runbooks/orchestrator-runtime.md`
- `docs/runbooks/streaming-sse.md`
- `docs/runbooks/webhooks-delivery.md`
- `docs/runbooks/chatkit-integration.md`
