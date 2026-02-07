# ChatKit Integration Runbook

## Scope
ChatKit advanced integration service (`POST /chatkit`) and thread-to-run execution behavior.

## Symptoms
- Chat UI cannot connect
- `POST /chatkit` returns `401` or `403`
- User messages do not start or resume runs
- Widgets/actions fail to resume interrupts

## Quick health checks
1. ChatKit service:
   - `curl -fsS http://127.0.0.1:8001/health`
2. Orchestrator service:
   - `curl -fsS http://127.0.0.1:8000/health`
3. Local ChatKit page:
   - `curl -fsS http://127.0.0.1:5183/chatkit.html`

## Logs to inspect
- `logs/chatkit.log`
- `logs/orchestrator.log`
- `logs/proxy.log`

## Common root causes
1. `CHATKIT_AUTH_TOKEN` mismatch between client and server.
2. Missing `workflow_id` in `threads.create` metadata.
3. Run not published or invalid workflow version reference.
4. Missing DB migrations for `chatkit_*` tables.
5. Idempotency conflict for repeated actions.

## Remediation steps
1. Re-apply migrations:
   - `./.venv/bin/python scripts/migrate.py`
2. Restart services:
   - `./scripts/dev_restart.sh`
3. Rebootstrap ChatKit workflow for local verification:
   - `./scripts/chatkit_up.sh`
4. Run ChatKit e2e from orchestrator service if Docker stack is used:
   - `./scripts/e2e_suite.sh`

## Verification
- Open `/chatkit.html`, provide valid `api_url`, `domain_key`, `workflow_id`.
- Send a message and confirm run starts.
- Trigger an interrupt and confirm widget/action resumes run.

## Escalation criteria
- Broad user inability to start chats
- Authentication bypass or token leakage
- Run state mismatch between ChatKit thread and orchestrator run
