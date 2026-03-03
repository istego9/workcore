# Webhooks

Date: 2026-03-03  
Status: Active

## Goal
Reliable inbound/outbound webhook processing with restart-safe persistence in Azure profile.

## Inbound
- Endpoint: `POST /webhooks/inbound/{integration_key}`
- Signature:
  - algorithm: HMAC SHA-256
  - payload: `{timestamp}.{raw_body}`
  - headers: `X-Webhook-Timestamp`, `X-Webhook-Signature`
- Idempotency:
  - optional `Idempotency-Key` header
  - scoped by `integration_key`
  - TTL-based dedupe
- Supported actions:
  - `start_run`
  - `resume_interrupt`

## Outbound
- Subscription lifecycle:
  - create
  - list
  - soft-delete (`is_active=false`)
- Event mapping:
  - `run_completed`
  - `run_failed`
  - `node_failed`
  - `interrupt_created` (derived from `run_waiting_for_input`)
- Dispatcher:
  - async HTTP delivery
  - exponential backoff retries
  - terminal failure after max attempts
  - delivery state tracking (`PENDING|SUCCESS|FAILED`)

## Store backends
### `memory` backend
- Default local development mode.
- No persistence across restarts.

### `postgres` backend
- Required for Azure deployment profile.
- Persists:
  - subscriptions -> `webhook_subscriptions`
  - deliveries -> `webhook_deliveries`
  - inbound keys -> `webhook_inbound_keys`
  - idempotency records -> `idempotency_keys` (webhook scope)
- Dispatcher recovery:
  - after restart, due deliveries are loaded from DB and retried.

## Configuration (env)
- `WEBHOOK_STORE_BACKEND=memory|postgres`
- `WEBHOOK_DEFAULT_INTEGRATION_KEY` (default: `default`)
- `WEBHOOK_DEFAULT_INBOUND_SECRET` (required for secure profile)

## Security notes
- Raw body is used for signature verification.
- Idempotency prevents duplicate side effects for retried inbound requests.
- Secrets are referenced via env/Key Vault and must not be logged.

## Compatibility
- Public endpoints and response envelopes remain unchanged.
- Backend persistence strategy is internal-only and additive.
