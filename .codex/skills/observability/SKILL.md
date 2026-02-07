---
name: observability
description: Add end-to-end observability: structured logs, metrics, traces, and correlation IDs across webhooks, chat actions, runs, nodes, and agent calls. Use when implementing critical paths or preparing for SLOs.
---

# Observability

## Requirements
- Propagate correlation IDs from request -> run -> node -> external calls.
- Add structured logs for state transitions.
- Emit metrics for latency and error rates per node type and endpoint.
- Link traces for agent calls.

## Steps
1) Define correlation fields and propagate them everywhere.
2) Add structured logging around:
   - Run state transitions
   - Node start/complete/fail
   - Interrupt create/resume
   - Webhook deliveries
3) Add metrics:
   - run_duration, node_duration
   - webhook_delivery_success/failure
   - sse_connections
4) Add dashboards and minimal alerts.

## Definition of done
- Answer "why did this run fail?" from logs and events in under 5 minutes.
- Latency/error metrics exist for core endpoints and node types.
