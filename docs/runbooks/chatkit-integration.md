# ChatKit Integration Runbook

## Scope
Chat-facing integration clients using canonical `POST /chat` and thread-to-run execution behavior.

## Symptoms
- Chat UI cannot connect.
- `POST /chat` returns `401` / `403` / `422`.
- User messages do not start or resume runs.
- Widgets/actions fail to resume interrupts.
- Integration doctor reports `FAIL`.

## Quick health checks
1. Chat service:
   - `curl -fsS http://127.0.0.1:8001/health`
2. Orchestrator service:
   - `curl -fsS http://127.0.0.1:8000/health`
3. Integration capabilities:
   - `curl -fsS http://127.0.0.1:8000/integration-capabilities | jq '.chat,.runtime_features'`
4. Integration doctor JSON:
   - `curl -fsS "http://127.0.0.1:8000/agent-integration-test.json?project_id=<project_id>" | jq '.summary,.checks[] | {id,status,code}'`
5. Local chat page:
   - `curl -fsS http://127.0.0.1:5183/chatkit.html`

## Required request contract (client-side)
- Headers:
  - required: `Authorization`, `X-Tenant-Id`, `X-Correlation-Id`
  - recommended: `X-Project-Id`, `X-Trace-Id`
- Thread creation scope resolution order:
  1. `metadata.workflow_id`
  2. `metadata.project_id`
  3. `X-Project-Id`
- Endpoint:
  - canonical: `POST /chat`
  - deprecated alias: `POST /chatkit` (must not be used in production flows)

## Logs to inspect
- `logs/chatkit.log`
- `logs/orchestrator.log`
- `logs/proxy.log`
- client-side logs: endpoint + `correlation_id` + `trace_id` + typed error `code/category`

## Common root causes
1. `CHATKIT_AUTH_TOKEN` mismatch between client and server.
2. Missing tenant/correlation headers in client requests.
3. Missing chat scope (`workflow_id` and project scope both absent).
4. Integration host policy mismatch (`integration_manifest.host_policy`) for pinned partners.
5. Client still calling legacy `/chatkit` endpoint.
6. Doctor report contains `FAIL` checks (integration must be treated as not ready).
7. Typed validation failures ignored (`error.bad_fields` not surfaced).

## Remediation steps
1. Re-apply migrations:
   - `./.venv/bin/python scripts/migrate.py`
2. Restart services:
   - `./scripts/dev_restart.sh`
3. Rebootstrap chat workflow for local verification:
   - `./scripts/chatkit_up.sh`
4. Validate capabilities + doctor:
   - `curl -fsS http://127.0.0.1:8000/integration-capabilities | jq`
   - `curl -fsS "http://127.0.0.1:8000/agent-integration-test.json?project_id=<project_id>" | jq`
5. Confirm host policy source-of-truth from onboarding bundle:
   - `curl -fsS http://127.0.0.1:8000/agent-integration-kit.json | jq '.integration_manifest.host_policy,.integration_manifest.auth_profile'`

## Verification
- Open `/chatkit.html` or `/chat-fork.html`.
- Provide `api_url`, tenant scope, and either `workflow_id` or `project_id`.
- Send a message and confirm run starts.
- Trigger an interrupt and confirm widget/action resumes run.
- Confirm client logs include `correlation_id` and `trace_id`.
- Confirm no production calls to `/chatkit` endpoint.
- For project-only flow: omit `workflow_id`, set `project_id`, verify default chat workflow resolution.

## Escalation criteria
- Broad user inability to start chats.
- Authentication bypass or token leakage.
- Run state mismatch between chat thread and orchestrator run.
- Doctor `FAIL` persists after host policy/auth/profile correction.
