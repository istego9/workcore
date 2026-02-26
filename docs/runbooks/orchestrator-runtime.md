# Orchestrator Runtime Runbook

## Scope
Workflow execution API/runtime service (`apps/orchestrator`), including run state and interrupt lifecycle.

## Symptoms
- `POST /workflows/{id}/runs` fails or hangs
- Run status is stuck in `RUNNING` or `WAITING_FOR_INPUT` unexpectedly
- Interrupt resume/cancel endpoints return errors
- SSE stream does not emit expected progress events

## Quick health checks
1. API health:
   - `curl -fsS http://127.0.0.1:8000/health`
2. ChatKit health (if affected):
   - `curl -fsS http://127.0.0.1:8001/health`
3. Builder local UI (if full dev stack):
   - `curl -fsS http://127.0.0.1:5183/`
4. MCP bridge health (if MCP nodes are used):
   - `curl -fsS http://127.0.0.1:8002/health`
5. Colima storage health (local Docker on Colima):
   - `./scripts/colima_storage_check.sh`

## Logs to inspect
- `logs/orchestrator.log`
- `logs/chatkit.log`
- `logs/proxy.log`

Tail commands:
- `tail -n 200 logs/orchestrator.log`
- `tail -n 200 logs/chatkit.log`

## LLM env checklist
- OpenAI path:
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
- Azure OpenAI path:
  - `AZURE_OPENAI_API_KEY`
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_API_VERSION`
  - `OPENAI_MODEL` must be Azure deployment name.
- Optional Agents SDK mode override:
  - `OPENAI_API=responses` or `OPENAI_API=chat_completions`

## Common root causes
1. Missing or invalid env vars (`DATABASE_URL`, auth tokens, external integration config)
2. Migrations not applied (`db/migrations/*.sql`)
3. Invalid workflow draft structure reaching runtime
4. External dependency failure (webhook target, model/tool endpoint)
5. Idempotency conflicts on repeated run/action requests
6. Colima VM ext4 storage issues (`/dev/vdb1`), which can surface as Postgres I/O errors
   - Example: `could not open file "global/pg_filenode.map": I/O error`
7. MCP bridge misconfiguration (`MCP_BRIDGE_BASE_URL` missing in runtime or bridge upstream not configured)

## Remediation steps
1. If Colima storage check fails, repair ext4 metadata and restart VM:
   - `./scripts/colima_repair_vdb1.sh`
2. Re-apply migrations:
   - `./.venv/bin/python scripts/migrate.py`
3. Restart local services:
   - `./scripts/dev_restart.sh`
4. Re-run smoke checks:
   - `./scripts/dev_check.sh`
5. Validate MCP bridge env when MCP nodes fail:
   - API/ChatKit runtime: `MCP_BRIDGE_BASE_URL`, `MCP_BRIDGE_AUTH_TOKEN`
   - MCP bridge service: `MCP_BRIDGE_UPSTREAM_CALL_URL`, optional allowlists
6. Validate problematic workflow via API docs/schema and republish if needed.

## Verification
- Create/publish a smoke workflow.
- Start a test run and confirm status progresses.
- Confirm expected events via `/runs/{run_id}/stream`.

## Escalation criteria
- Reproducible failures affecting all tenants or all runs
- Data integrity issues in persisted run state
- Security concerns (auth bypass, secret leakage)
