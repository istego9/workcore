# ADR-0004: Postgres + Object Storage

Date: 2026-01-29
Status: Accepted

## Context
We need durable storage for workflow metadata, run state, node outputs, and user uploads.

## Decision
Use Postgres as the system of record and object storage for large artifacts and files.

## Consequences
- Relational queries and transactional guarantees for workflow/run metadata.
- Large payloads and uploads are stored outside the database with references.
- We must operate Postgres and a self-hosted object store (S3-compatible).

## Alternatives Considered
- Single store (Postgres only): large objects increase DB bloat and backup cost.
- NoSQL-only: weaker transactional guarantees for workflow/runs.
