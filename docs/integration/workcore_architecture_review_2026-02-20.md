# WorkCore Architecture Review (2026-02-20)

Status: Draft for team alignment
Scope: orchestrator routing/custom-action stream (`origin/main..HEAD` on `codex/workcore-p0-routing-custom-actions`)
Task class: F (review/documentation only)

## 1) Findings (ordered by severity)

### P0 - `integration_http` allows unrestricted outbound targets (SSRF/exfiltration surface)
- Impact:
  - Any workflow author can configure requests to arbitrary URLs, including internal services/metadata endpoints.
  - This violates least privilege and introduces high-severity data exfiltration risk.
- Evidence:
  - `apps/orchestrator/executors/integration_http_executor.py:92` sends requests directly to `config.url`.
  - `apps/orchestrator/executors/integration_http_executor.py:96` only validates non-empty URL; no host/scheme/IP policy.
  - `docs/integration/workcore_routing_custom_actions_unification_action_items.md:147` still tracks outbound allowlist/guardrails as TODO.
- Recommendation:
  - Add deny-by-default outbound policy (allowlist domains/CIDRs/schemes).
  - Block link-local/private-network targets by default.
  - Add explicit per-tenant/per-project policy surface and audit logs for blocked targets.

### P1 - Blocking I/O in runtime execution path reduces throughput and can starve event loop
- Impact:
  - `integration_http` execution performs blocking network calls and `sleep`, while orchestrator runtime methods are async entrypoints.
  - Under load/retries this can degrade latency for unrelated requests.
- Evidence:
  - `apps/orchestrator/executors/integration_http_executor.py:59` uses synchronous `httpx.Client` context manager.
  - `apps/orchestrator/executors/integration_http_executor.py:79` uses blocking `time.sleep` backoff.
  - `apps/orchestrator/runtime/multi_service.py:105` runs `engine.execute_until_blocked(run)` inline in async flow.
- Recommendation:
  - Move `integration_http` execution to async path (`httpx.AsyncClient` + `await asyncio.sleep`) or run sync executor in dedicated worker/thread pool.
  - Add latency SLO alerts by node type (`integration_http`) and retry count percentile dashboards.

### P1 - ChatKit idempotency key can get stuck on validation/unsupported-action early returns
- Impact:
  - Client may receive `Action already processed` for retriable user correction attempts until TTL expires.
  - This degrades interaction reliability for forms/custom submit actions.
- Evidence:
  - Idempotency starts at `apps/orchestrator/chatkit/server.py:137`.
  - Early returns without `fail()` on submit payload validation error at `apps/orchestrator/chatkit/server.py:147` and `apps/orchestrator/chatkit/server.py:151`.
  - Early return for unsupported cancel action at `apps/orchestrator/chatkit/server.py:152` and `apps/orchestrator/chatkit/server.py:154`.
- Recommendation:
  - Ensure all post-`start()` early exits call `idempotency.fail(...)` (or postpone `start()` until after validation).
  - Add regression tests for repeated submit attempts after payload validation errors.

### P2 - OpenAPI/status behavior drift for context endpoints
- Impact:
  - Generated clients can expect `422` while implementation currently returns `400` for validation errors.
  - Causes avoidable integration ambiguity.
- Evidence:
  - OpenAPI includes `422` for context endpoints at `docs/api/openapi.yaml:401`, `docs/api/openapi.yaml:428`, `docs/api/openapi.yaml:455`.
  - API returns `400` for payload validation paths in `apps/orchestrator/api/app.py:2111`, `apps/orchestrator/api/app.py:2135`, `apps/orchestrator/api/app.py:2197`.
- Recommendation:
  - Pick one contract (`400` or `422`) and align OpenAPI + implementation + tests.

### P2 - High concentration in two large modules slows review and autonomous edits
- Impact:
  - Larger merge conflicts, slower root-cause analysis, weaker boundary clarity for agents.
- Evidence:
  - `apps/orchestrator/api/app.py` is 3452 lines.
  - `apps/orchestrator/orchestrator_runtime/runtime.py` is 1272 lines.
- Recommendation:
  - Extract route groups and orchestrator policy/action handlers into focused modules with stable boundaries and test ownership.

## 2) Commit trend analysis (latest stream)

Positive signals:
- Strong spec-first discipline in latest 6 feature slices (`spec -> feat` adjacency pairs).
- Tests were added in the same stream for API/chatkit/engine/executor/store context.
- Public API changes were versioned through changelog increments (`0.11.0 -> 0.16.0`).

Risk signals:
- Reliability and policy complexity are growing faster than operational guardrails (security egress policy and harness-gated quality are not yet hard merge gates).
- Runtime behavior expanded quickly (routing policies + replay eval + custom action normalization) while module boundaries stayed monolithic.

## 3) Alignment with Harness Engineering (OpenAI)

Mapped principles from Harness Engineering to WorkCore:
- Reduce conversion entropy:
  - Keep tasks crisp and schema-first (already strong in recent commits).
  - Add canonical task templates for agent work items (input contract + output artifact contract).
- Build robust harnesses:
  - Current `POST /orchestrator/eval/replay` is a good primitive; it should become a CI quality gate with golden datasets and threshold policy.
- Optimize measurable loops:
  - Treat routing quality (`action_accuracy`, `workflow_accuracy`, `exact_match_rate`) as release criteria, not only diagnostics.

Source:
- https://openai.com/index/harness-engineering/

## 4) Optimization program (cost/quality/speed)

### Immediate (1-2 days)
- [ ] Fix idempotency early-return behavior in ChatKit custom actions.
- [ ] Define and enforce outbound URL policy for `integration_http` (minimum deny-list for local/internal networks).
- [ ] Align `400/422` behavior for context endpoints.

### Short term (1-2 weeks)
- [ ] Add routing-harness CI job using stable replay cases:
  - store cases under `apps/orchestrator/tests/fixtures/routing_eval/*.json`
  - fail CI when metrics regress below agreed threshold.
- [ ] Split `api/app.py` into route modules (`projects`, `orchestrator`, `workflows`, `runs`, `webhooks`).
- [ ] Split orchestrator runtime policy/resolution/action execution into separate modules.

### Mid term (2-4 weeks)
- [ ] Add observability pack for routing quality and `integration_http` behavior:
  - p50/p95/p99 latency by node type and retry count
  - switch-policy block reasons distribution
  - replay/eval trend dashboard by commit SHA
- [ ] Add architecture ADR for routing policy precedence + replay-eval governance.

## 5) Agent autonomy documentation gaps

To maximize autonomous, high-quality agent execution, add one canonical playbook that combines:
- strict task intake contract,
- harness-first loop,
- required evidence artifacts,
- stop conditions and escalation rules.

Proposed file:
- `docs/architecture/agent-autonomy-harness.md`

