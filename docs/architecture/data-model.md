# Data Model (Phase 1)

Date: 2026-01-29
Status: Draft

This document defines the MVP persistence model for a self-hosted deployment.

## Storage choices
- Primary database: Postgres.
- Object storage: S3-compatible (self-hosted, e.g., MinIO).
- Event bus: Kafka (self-hosted).
- Secrets manager: self-hosted (e.g., Vault) for integration credentials and webhook secrets.

## ID strategy
- Use application-generated string IDs with prefixes where useful (e.g., wf_, run_, intr_).
- All tables include tenant_id for multi-tenancy.

## Core tables

### workflows
Holds workflow metadata and the editable draft.
- id (text, pk)
- tenant_id (text, indexed)
- name (text)
- description (text, nullable)
- draft (jsonb)  // nodes, edges, variables_schema
- active_version_id (text, fk -> workflow_versions.id, nullable)
- created_at, updated_at (timestamptz)

### workflow_versions
Immutable published versions of workflows.
- id (text, pk)
- workflow_id (text, fk -> workflows.id)
- tenant_id (text, indexed)
- version_number (int)
- hash (text)
- content (jsonb)
- created_at (timestamptz)

Unique: (workflow_id, version_number)

### runs
Execution instances pinned to a specific published version.
- id (text, pk)
- workflow_id (text, fk)
- version_id (text, fk -> workflow_versions.id)
- tenant_id (text, indexed)
- status (text)
- mode (text, default live)
- inputs (jsonb)
- state (jsonb)
- outputs (jsonb, nullable)
- node_outputs (jsonb) // per-node outputs for expression context
- branch_selection (jsonb) // branch node -> selected target
- loop_state (jsonb) // while node -> iteration counter
- skipped_nodes (jsonb) // array of skipped node ids
- correlation_id (text, nullable)
- created_at, updated_at, started_at, completed_at (timestamptz)

### node_runs
Execution state per node in a run.
- id (text, pk)
- run_id (text, fk -> runs.id)
- node_id (text)
- status (text)
- attempt (int)
- output (jsonb, nullable)
- last_error (jsonb, nullable)
- trace_id (text, nullable)
- usage (jsonb, nullable)
- started_at, completed_at (timestamptz)
- created_at, updated_at (timestamptz)

Unique: (run_id, node_id, attempt)

### interrupts
Paused execution waiting for external input.
- id (text, pk)
- run_id (text, fk -> runs.id)
- node_id (text)
- tenant_id (text, indexed)
- type (text)  // approval, form, file_upload
- status (text) // OPEN, RESOLVED, CANCELLED, EXPIRED
- prompt (text)
- input_schema (jsonb, nullable)
- allow_file_upload (bool)
- input (jsonb, nullable)
- files (jsonb, nullable) // file refs
- state_target (text, nullable) // path in state to write resolved interrupt input
- expires_at (timestamptz, nullable)
- created_at, updated_at, resolved_at (timestamptz)

### files
References to objects in object storage.
- id (text, pk)
- tenant_id (text, indexed)
- object_key (text)
- content_type (text)
- size_bytes (bigint)
- sha256 (text)
- created_at (timestamptz)

### events
Durable event log for SSE replay and auditing.
- id (text, pk)
- run_id (text, indexed)
- workflow_id (text)
- version_id (text)
- node_id (text, nullable)
- tenant_id (text, indexed)
- type (text)
- payload (jsonb)
- correlation_id (text, nullable)
- created_at (timestamptz)

### webhook_subscriptions
Outbound webhook registrations.
- id (text, pk)
- tenant_id (text, indexed)
- url (text)
- event_types (text[])
- secret_ref (text) // stored in secrets manager
- is_active (bool)
- created_at, updated_at (timestamptz)

### webhook_deliveries
Outbound delivery attempts.
- id (text, pk)
- subscription_id (text, fk -> webhook_subscriptions.id)
- event_id (text, nullable)
- event_type (text)
- payload (jsonb)
- status (text) // PENDING, SUCCESS, FAILED
- attempt_count (int)
- last_error (text, nullable)
- next_retry_at (timestamptz, nullable)
- created_at, updated_at (timestamptz)

### webhook_inbound_keys
Inbound webhook authentication keys.
- id (text, pk)
- tenant_id (text, indexed)
- integration_key (text, unique)
- secret_ref (text) // stored in secrets manager
- is_active (bool)
- created_at, updated_at (timestamptz)

### idempotency_keys
Idempotency store for non-safe operations (runs, interrupts, inbound webhooks, chat actions).
- id (text, pk)
- tenant_id (text, indexed)
- idempotency_key (text)
- scope (text) // endpoint or operation name
- request_hash (text)
- response_body (jsonb, nullable)
- status (text) // IN_PROGRESS, COMPLETED, FAILED
- expires_at (timestamptz)
- created_at (timestamptz)

Unique: (tenant_id, idempotency_key, scope)

## Indexing notes
- runs: index by (workflow_id, status, created_at).
- node_runs: index by (run_id, status).
- events: index by (run_id, created_at).
- webhook_deliveries: index by (status, next_retry_at).
- idempotency_keys: index by (tenant_id, idempotency_key, scope), (expires_at).

## Headless testing
All UI/E2E tests run headless by default in CI. No GUI dependencies are assumed for automated pipelines.
