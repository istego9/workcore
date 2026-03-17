# Service Conformance Handoff 2026-03-17

Use this checklist when handing WorkCore integration updates to external service teams. This artifact is a handoff template, not an in-repo rollout board.

## Required checks per consuming service
1. Canonical chat path uses `POST /chat`; deprecated `/chatkit` is not used in production flows.
2. Client handles typed platform errors via `error.code`, `category`, `retryable`, `retry_after_s`, `bad_fields`, `unsupported_feature`, `docs_ref`, and `correlation_id`.
3. Client reads `GET /integration-capabilities` and does not infer capabilities from text-only docs.
4. Client respects `integration_manifest.host_policy` for canonical base URL and allowed domains.
5. Service can produce an `agent-integration-test.json` doctor verdict with no `FAIL` checks.
6. Project-scoped chat uses `projects.settings.default_chat_workflow_id` where applicable.
7. Direct orchestrator mode registers workflow routing explicitly via `POST /projects/{project_id}/workflow-definitions` and can read it back via `GET /projects/{project_id}/workflow-definitions/{workflow_id}`.

## Evidence to request from each team
1. Service/repo name and owner.
2. Current production API base URL.
3. Proof that `/chat` is used instead of `/chatkit`.
4. Example typed error payload captured by the client.
5. `GET /integration-capabilities` response snapshot or parsed capability record used by the client.
6. Latest doctor verdict (`PASS`, `WARN`, or `FAIL`) with failing check IDs if not `PASS`.
7. For direct routing flows: proof of workflow-definition readback after bind.

## Suggested handoff table
| Service | Owner | `/chat` cutover | Typed errors | Capabilities | Host policy | Doctor | Direct routing readback | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| example-service | owner@example.com | PASS | PASS | PASS | PASS | WARN | PASS | Replace WARN with concrete follow-up |
