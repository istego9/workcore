---
name: spec-first-control
description: >
  Enforce Spec-First execution for this repository. Use when changes touch OpenAPI, JSON schemas,
  DB migrations, event payloads, runtime semantics, or service boundaries.
---

# Spec-First Control

## Goal
Prevent implementation drift from product/API/runtime specifications.

## Triggers
- API contract changes
- JSON schema changes
- DB schema or migration changes
- Streaming/event payload changes
- Workflow runtime semantics changes

## Required artifacts (update before code)
- `docs/api/openapi.yaml`
- `docs/api/schemas/*.json`
- `db/migrations/*.sql`
- `docs/architecture/*.md` and/or `docs/adr/*.md` when behavior changes

## Mandatory action items
1) Goal and scope
2) Exact spec files to change
3) Compatibility strategy (additive/breaking)
4) Implementation files
5) Tests to add/update
6) Observability/security impacts
7) Rollout/rollback notes
8) Open questions/TODOs

## Workflow
1) Classify task (A-G from `AGENTS.md`).
2) For A-E, update spec artifacts first.
3) Implement code changes.
4) Add/update tests (unit/integration/contract/e2e as applicable).
5) Update docs and summarize residual risks.

## Guardrails
- Do not invent undocumented fields.
- Do not merge contract/schema changes without tests.
- If information is missing, add TODO + request clarification.
