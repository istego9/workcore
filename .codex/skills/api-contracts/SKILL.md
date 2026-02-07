---
name: api-contracts
description: Design or update public APIs with OpenAPI-first schemas, consistent error envelopes, pagination, idempotency, and backward compatibility. Use when adding or changing endpoints for workflows, runs, interrupts, streaming, or webhooks.
---

# API Contracts

## Required outputs
- Update OpenAPI specs (or the contract source of truth).
- Provide example requests/responses for key endpoints.
- Add contract tests or schema validation tests.

## Guidelines
- Define schema before implementation.
- Use a single error envelope: error.code, error.message, error.details (optional), correlation_id.
- Support idempotency for non-safe operations (POST run start, inbound webhooks, chat actions).

## Steps
1) Enumerate endpoints and responsibilities:
   - Workflows: create/get/update-draft/publish/rollback/versions
   - Runs: start/get/list/cancel/rerun-node/stream
   - Interrupts: resume/cancel
   - Webhooks: register/list/delete + inbound receiver
2) Define schemas:
   - WorkflowDraft (nodes, edges, variables schema)
   - PublishedVersion
   - Run / NodeRun / Interrupt
   - Event (SSE payload)
3) Add compatibility notes:
   - Mark additive vs breaking changes
   - Define deprecation strategy when needed
4) Implement schema validation at boundaries.

## Definition of done
- Ensure the spec validates/compiles.
- Include minimal examples for each endpoint.
- Ensure contract tests exist (or API schema validation is enforced in CI).
