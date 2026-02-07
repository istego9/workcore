# Webhooks (Phase 5)

Date: 2026-01-29
Status: Draft

## Inbound
- Endpoint: `POST /webhooks/inbound/{integration_key}`
- Signature: HMAC SHA-256 over `{timestamp}.{body}`
- Headers: `X-Webhook-Timestamp`, `X-Webhook-Signature`
- Idempotency: `Idempotency-Key` header with TTL

## Outbound
- Subscriptions: create/list/delete
- Delivery: retries with exponential backoff, max attempts
- Events: run_completed, run_failed, node_failed, interrupt_created

## Implementation notes
- Signatures are validated with replay protection (timestamp tolerance).
- Outbound dispatcher sends JSON payloads and records delivery status.
