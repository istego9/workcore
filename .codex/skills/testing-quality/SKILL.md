---
name: testing-quality
description: Create a systematic test suite (unit, integration, contract, E2E) for workflows, streaming, chat actions, and webhooks. Use when adding major capabilities or touching critical orchestration logic.
---

# Testing Quality

## Test layers
- Unit: pure functions, validators, expression evaluation, mapping layers.
- Integration: orchestrator + DB + queue + SSE.
- Contract: OpenAPI schema + consumer-driven tests if applicable.
- E2E: builder -> publish -> run -> interrupt -> resume -> completion.

## Steps
1) Define "golden workflows" fixtures:
   - Minimal linear workflow
   - Branch workflow (if/else)
   - Loop workflow (while with max_iterations)
   - Interrupt workflow (approval/file upload)
2) Implement deterministic fakes/mocks:
   - Agent executor stub for predictable outputs
   - MCP stub server
   - Webhook receiver test server
3) Add CI gating:
   - Schema validation
   - Integration tests
   - Minimal E2E smoke test

## Definition of done
- CI catches broken publish/run/interrupt semantics.
- At least one E2E test covers chat action resume.
- Streaming and webhooks have integration coverage.
