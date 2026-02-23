# WorkCore Runtime Async Execution + DNS Guardrails Action Items

Date: 2026-02-20
Status: DONE
Task classification: C (runtime semantics), E (external integration behavior)

## 1) Goal and scope
- [x] Move blocking workflow execution path off the main asyncio event loop for runtime service calls.
- [x] Add DNS resolution checks for `integration_http` egress policy and enforce CIDR-based deny rules on resolved IPs.
- [x] Preserve existing `integration_http` node contract (no request/response schema changes).

Out of scope:
- [x] Full engine async refactor (async handlers in `OrchestratorEngine`).
- [x] Per-tenant DB-backed egress policy storage.

## 2) Spec files to update (exact paths)
- [x] `docs/architecture/runtime.md`
- [x] `docs/architecture/executors.md`
- [x] `docs/api/reference.md`

## 3) Compatibility strategy (additive vs breaking)
- [x] Additive behavior hardening:
  - runtime scheduling remains API-compatible;
  - `integration_http` requests may now be blocked when resolved IPs match private/local or denied CIDRs.
- [x] No public endpoint payload changes.

## 4) Implementation files
- [x] `apps/orchestrator/executors/integration_http_executor.py`
- [x] `apps/orchestrator/runtime/multi_service.py`
- [x] `apps/orchestrator/runtime/service.py`
- [x] `apps/orchestrator/chatkit/runtime_service.py`
- [x] `apps/orchestrator/api/app.py`
- [x] `.env.example`
- [x] `.env.docker.example`

## 5) Tests (unit/integration/contract/e2e)
- [x] Extend `apps/orchestrator/tests/test_integration_http_executor.py` with DNS/CIDR policy cases.
- [x] Add async runtime non-blocking regression coverage for workflow execution path.
- [x] Run relevant test suites.

## 6) Observability/security impacts
- [x] Security: DNS rebinding/internal-address routing is explicitly blocked by resolved-IP policy.
- [x] Reliability: blocking executor calls no longer stall main event loop in runtime service entrypoints.

## 7) Rollout/rollback notes
- [x] Rollout: configure `INTEGRATION_HTTP_DENY_CIDRS` (optional hard deny overlay).
- [x] Rollback: revert runtime offload + DNS/CIDR checks if critical integration incompatibility is discovered.

## 8) Outstanding TODOs/questions
- [x] Decide if DNS resolution results should be cached with TTL for high-throughput environments.
- [x] Decide if CIDR policies should become tenant/project scoped instead of env-scoped.
