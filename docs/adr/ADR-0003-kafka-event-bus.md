# ADR-0003: Kafka Event Bus

Date: 2026-01-29
Status: Accepted

## Context
We need a durable event bus for run progress, SSE replay, and fan-out to consumers.

## Decision
Use self-hosted Kafka for the event bus, partitioned by run_id.

## Consequences
- Per-run ordering is preserved via partitioning.
- We must operate Kafka clusters and manage retention and compaction policies.
- Consumers must handle replays and idempotent processing.

## Alternatives Considered
- Redis Pub/Sub: low latency but lacks durable replay guarantees.
- NATS or RabbitMQ: viable but not selected for this phase.
