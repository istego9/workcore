# Streaming SSE Runbook

## Scope
Run event streaming via `GET /runs/{run_id}/stream`, replay, and `Last-Event-ID` handling.

## Symptoms
- SSE stream disconnects or stalls
- UI does not show run progress
- Reconnect does not replay expected events
- Event ordering appears incorrect for a run

## Quick health checks
1. API health:
   - `curl -fsS http://127.0.0.1:8000/health`
2. Stream endpoint basic check:
   - `curl -N "http://127.0.0.1:8000/runs/<run_id>/stream" -H "X-Tenant-Id: local"`
3. Reconnect behavior check:
   - `curl -N "http://127.0.0.1:8000/runs/<run_id>/stream" -H "X-Tenant-Id: local" -H "Last-Event-ID: <event_id>"`

## Logs and data to inspect
- `logs/orchestrator.log`
- `logs/chatkit.log` (if stream consumed via ChatKit)
- `events` table entries for the run (sequence and timestamps)

Example query:
- `psql "$DATABASE_URL" -c "select id, run_id, type, sequence, created_at from events where run_id = '<run_id>' order by created_at;"`

## Common root causes
1. Missing or invalid tenant header (`X-Tenant-Id`).
2. Event persistence gaps caused by runtime failures before publish.
3. Incorrect `Last-Event-ID` during reconnect.
4. Streaming backend misconfiguration (`STREAMING_BACKEND`, Kafka env vars).

## Remediation steps
1. Confirm run exists and has events:
   - `GET /runs/{run_id}`
   - query `events` table
2. Restart local services:
   - `./scripts/dev_restart.sh`
3. Re-run streaming tests:
   - `./.venv/bin/python -m pytest apps/orchestrator/tests/test_streaming.py -q`

## Verification
- Start a new run.
- Observe `run_started` -> node events -> terminal run event in stream.
- Reconnect with `Last-Event-ID` and confirm replay continuity.

## Escalation criteria
- Missing terminal events (`run_completed`/`run_failed`) for active runs
- Multi-tenant event leakage
- Systemic stream disconnects impacting multiple runs
