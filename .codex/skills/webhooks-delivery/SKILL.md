---
name: webhooks-delivery
description: Implement inbound/outbound webhooks with signatures, idempotency, retries, delivery logs, and DLQ behavior. Use when adding webhook triggers/callbacks or hardening reliability/security.
---

# Webhooks Delivery

## Inbound requirements
- Verify signature (HMAC + timestamp).
- Enforce replay protection window.
- Support idempotency keys.

## Outbound requirements
- Retry deliveries with exponential backoff.
- Persist delivery logs (status, attempts, last_error).
- Dead-letter after max attempts.

## Steps
1) Design webhook payload envelopes and headers.
2) Implement signature verification middleware.
3) Implement inbound handlers:
   - Validate payload
   - Dedupe by idempotency key
   - Enqueue/trigger internal action
4) Implement outbound dispatcher:
   - Queue-based delivery worker
   - Retries + DLQ
5) Add integration tests using a fake receiver server.

## Definition of done
- Inbound rejects invalid signatures.
- Outbound retries on 5xx/timeouts and records delivery history.
- Exactly-once semantics are approximated via idempotency keys.
