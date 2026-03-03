# Webhooks Delivery Runbook

## Scope
Inbound webhooks (`POST /webhooks/inbound/{integration_key}`) and outbound subscription delivery/retries.

## Symptoms
- Inbound webhook rejected (`401`, `403`, `400`)
- Outbound events not delivered to subscribers
- Repeated delivery failures and retry backlog
- Duplicate processing despite idempotency keys

## Quick health checks
1. API health:
   - `curl -fsS http://127.0.0.1:8000/health`
2. Inbound endpoint reachability:
   - `curl -i -X POST "http://127.0.0.1:8000/webhooks/inbound/<integration_key>" -H "Content-Type: application/json" -d '{}'`
3. Subscription list:
   - `GET /webhooks/subscriptions` with tenant/auth headers
4. Backend mode check:
   - `echo "$WEBHOOK_STORE_BACKEND"` (should be `postgres` in Azure profile)

## Logs and data to inspect
- `logs/orchestrator.log`
- `webhook_deliveries` table (status, attempts, next retry)
- `idempotency_keys` table entries for webhook scopes

Example query:
- `psql "$DATABASE_URL" -c "select id, event_type, status, attempt_count, next_retry_at, last_error from webhook_deliveries order by created_at desc limit 50;"`

Additional queries:
- Active subscriptions:
  - `psql "$DATABASE_URL" -c "select id, url, event_types, is_active from webhook_subscriptions where is_active = true order by created_at desc;"`
- Inbound keys:
  - `psql "$DATABASE_URL" -c "select integration_key, is_active, updated_at from webhook_inbound_keys order by updated_at desc;"`

## Common root causes
1. Invalid or missing webhook signature headers.
2. Clock skew beyond timestamp tolerance in signature verification.
3. Inactive/misconfigured subscription URL.
4. Target endpoint timeout or persistent `5xx`.
5. Idempotency key reuse with mismatched payload hash.
6. Volatile webhook backend in production (`WEBHOOK_STORE_BACKEND=memory`).

## Remediation steps
1. Verify inbound signing inputs:
   - timestamp header
   - HMAC secret reference
   - exact raw request body
2. Confirm subscription and secret configuration for tenant.
3. Retry from dispatcher path after fixing receiver issues.
4. Restart services if dispatcher workers are stuck:
   - `./scripts/dev_restart.sh`
5. Re-run webhook tests:
   - `./.venv/bin/python -m pytest apps/orchestrator/tests/test_webhooks.py -q`
6. For durable mode, restart orchestrator and confirm failed deliveries continue retrying from DB.

## Verification
- Send signed inbound webhook and confirm accepted response.
- Trigger a known outbound event (`run_completed` etc.).
- Confirm delivery status transitions to `SUCCESS`.

## Escalation criteria
- Continuous outbound failure for critical tenants
- Replay attack or signature verification bypass suspicion
- Data inconsistency from duplicate webhook processing
- Dispatcher fails to recover pending retries after process restart
