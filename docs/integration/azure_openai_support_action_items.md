# Azure OpenAI Support - Spec-First Action Items

Date: 2026-02-16
Status: COMPLETED
Task classification: E (external integration behavior change)

## 1) Goal and scope
- Add Microsoft Azure OpenAI support for:
  - Agent node execution (OpenAI Agents SDK path)
  - Intent routing LLM adapter (`ResponsesLLMRouter`)
- Preserve current OpenAI behavior by default.

Out of scope:
- Public API/OpenAPI changes.
- DB schema/migration changes.
- Runtime event payload changes.

## 2) Spec files to update (exact paths)
- `docs/architecture/executors.md`
- `docs/runbooks/orchestrator-runtime.md`
- `docs/deploy/docker-workcore-build.md`
- `.env.example`
- `.env.docker.example`

No changes planned:
- `docs/api/openapi.yaml`
- `docs/api/schemas/*.json`
- `db/migrations/*.sql`

## 3) Compatibility strategy (additive vs breaking)
- Additive only.
- Existing OpenAI path remains default when Azure env vars are not set.

## 4) Implementation files
- `apps/orchestrator/executors/agent_executor.py`
- `apps/orchestrator/llm_adapter/responses_router.py`

## 5) Tests (unit/integration/contract/e2e)
- Add/update orchestrator unit tests:
  - `apps/orchestrator/tests/test_llm_router.py`
  - `apps/orchestrator/tests/test_agent_executor_event_loop.py`
  - `apps/orchestrator/tests/test_agent_executor_integration.py`
- Run relevant checks:
  - `./.venv/bin/python -m pytest apps/orchestrator/tests/test_llm_router.py apps/orchestrator/tests/test_agent_executor_event_loop.py`

## 6) Observability/security impacts
- Do not log provider secrets (`OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`).
- Fail fast with explicit configuration error when Azure mode is partially configured.

## 7) Rollout/rollback notes
- Rollout: set Azure env vars in deployment environment and restart orchestrator/chatkit services.
- Rollback: remove Azure env vars and keep OpenAI env vars only.

## 8) Outstanding TODOs/questions
- TODO: Confirm target `AZURE_OPENAI_API_VERSION` per environment (kept explicit via env var).
