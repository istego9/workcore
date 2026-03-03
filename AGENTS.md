# AGENTS.md

## Project summary
This repository implements a workflow platform with:
- A visual workflow builder (graph editor) for composing workflows from nodes and edges.
- A backend orchestrator/runtime that executes published workflow versions as runs, persists state, supports interrupts, and streams progress events.
- A chat surface built with ChatKit where users can interact with runs (approval, forms, file uploads) via widgets/actions.
- AI agent execution via the OpenAI Agents SDK for "Agent" nodes.
- Integrations via inbound/outbound webhooks and optional MCP tools.

## Prime directive
**Spec-First change control.** If a task changes contracts, persisted state, event payloads, or module boundaries:
1) Update specification artifacts first.
2) Create explicit action items so no requirement is dropped.
3) Only then implement code.

Specification artifacts for this repo:
- API contract: `docs/api/openapi.yaml`
- JSON schemas: `docs/api/schemas/*.json`
- Persisted state and DB shape: `db/migrations/*.sql` + `docs/architecture/data-model.md`
- Runtime/event semantics: `docs/architecture/*.md` + relevant ADRs in `docs/adr/*.md`

If required information is missing:
- Do not invent fields/behaviors.
- Add explicit TODOs and ask for clarification.

## Non-negotiable working agreements
- Never commit secrets (API keys, tokens, credentials). Use a secrets manager and env vars.
- Keep changes small and reviewable. Prefer incremental PRs.
- Commit discipline is mandatory for AI-assisted work:
  - Every completed logical change must be committed immediately as a separate granular commit.
  - Do not leave AI-authored changes uncommitted at task handoff.
  - Do not mix unrelated concerns in one commit.
- Update or add tests for any behavior change.
- Document all public APIs (OpenAPI) and any breaking changes.
- For any public API contract update (`docs/api/openapi.yaml` or `docs/api/schemas/*.json`), update `CHANGELOG.md` in the same change.
- Each API changelog entry must explicitly describe the delta vs previous API version:
  - `Previous API version`
  - `Current API version`
  - concrete Added/Changed/Deprecated/Removed items
- Preserve backward compatibility for persisted data and public endpoints unless explicitly approved.

## Task classification (mandatory before coding)
A) New module/subsystem  
B) API contract change (OpenAPI or JSON schemas)  
C) Event payload/streaming semantics change  
D) DB schema/migration change  
E) External integration behavior change (webhooks/ChatKit/MCP/adapters)  
F) Refactor/docs only (no functional changes)  
G) Bugfix without contract/schema changes

For A-E: Spec-First is mandatory.

## Action items requirement (mandatory for specification tasks)
For A-E tasks, create and track this checklist in task notes/PR description:
1) Goal and scope
2) Spec files to update (exact paths)
3) Compatibility strategy (additive vs breaking)
4) Implementation files
5) Tests (unit/integration/contract/e2e)
6) Observability/security impacts
7) Rollout/rollback notes
8) Outstanding TODOs/questions

## Repository conventions
- Prefer the existing stack, libraries, and patterns in this repository.
- If a new module is required in a greenfield area, propose the smallest viable dependency set and ask before adding production dependencies.
- Use a consistent error model across APIs (`error.code`, `error.message`, optional details, `correlation_id`).
- Do not introduce GraphQL-only process requirements in this repository unless GraphQL is actually introduced.

## Mandatory checks (adapt by touched area)
Run what is relevant to the change:
- `./scripts/archctl_validate.sh`
- `./.venv/bin/python -m pytest apps/orchestrator/tests`
- `cd apps/builder && npm run test:unit`
- `cd apps/builder && npm run test:e2e` (required when UI/runtime integration paths are touched)
- `./scripts/dev_check.sh` for local health + smoke

If a check cannot run locally, state exactly why and what remains to validate.

## Definition of Done (applies to all tasks)
A task is done when:
- Implementation builds and relevant tests pass.
- Public behavior is documented (OpenAPI/spec/docs).
- Observability is included (logs/metrics/traces or equivalent).
- No secrets or sensitive payloads are logged by default.
- Services are restarted for affected components.
- Relevant E2E/smoke checks are executed.

## Process artifacts (operational)
- Quality scoreboard: `docs/QUALITY_SCORE.md`
- Security baseline: `docs/SECURITY.md`
- Reliability baseline: `docs/RELIABILITY.md`
- Execution plans and tech debt tracker: `docs/exec-plans/`

## Skills available in this repo
Skills are stored under `.codex/skills/<skill-name>/SKILL.md`. Codex can invoke them explicitly (e.g., `$api-contracts`) or implicitly by matching descriptions.

### Domain skills
- $platform-architecture: system boundaries, event taxonomy, ADRs.
- $api-contracts: OpenAPI-first endpoints, schemas, error model, versioning.
- $workflow-runtime: orchestrator execution semantics, runs, node statuses, state model.
- $workflow-versioning: draft/published, publish/rollback, pinned run versions, migrations.
- $streaming-sse: server-sent events for run progress, reconnect semantics, event schema.
- $webhooks-delivery: inbound/outbound webhooks, signatures, idempotency, retries, DLQ.
- $agents-sdk-executor: implement Agent node execution using OpenAI Agents SDK, streaming, schemas.
- $chatkit-server: ChatKit advanced integration server, sessions, threading, message streaming.
- $chatkit-widgets-actions: widgets/actions for interaction, approval, forms, file upload, resume.
- $workflow-builder-ui: graph editor UI, palette, config panels, validation, persistence.
- $mcp-integration: MCP tool execution (remote or direct), auth and guardrails.
- $testing-quality: test strategy, integration/E2E, contract tests, fixtures, load tests.
- $security-governance: RBAC, secrets, audit logs, PII redaction policies.
- $observability: traces/metrics/logs, correlation IDs, dashboards.
- $docs-adr: developer docs, runbooks, ADR templates, API docs.

### Process skills (high-value)
- $spec-first-control: enforce spec-first execution and compatibility notes.
- $architecture-review: boundary/dependency review before merge.
- $schema-migrations-postgres: safe, idempotent DB migration workflow.
- $ci-bootstrap: CI checks and merge gates.
- $incident-runbook: operational SOPs and postmortem templates.
- $commit-and-pr-hygiene: atomic commits and review-ready PRs.
- $ai-change-explainer: auditable summary for large diffs.
- $acceptance-package: build acceptance package artifacts (`ACCEPTANCE.md`, Playwright desktop/mobile screenshots, ZIP) for handoff/review.

## How to start on any task
1) Identify and invoke relevant skills.
2) Classify task (A-G) and create action items for A-E.
3) Update specs first for A-E tasks.
4) Implement with tests.
5) Update docs and verify Definition of Done.

---

References:
- https://developers.openai.com/codex/skills/
- https://developers.openai.com/codex/guides/agents-md/
- https://developers.openai.com/codex/skills/create-skill/
- https://developers.openai.com/blog/eval-skills/
