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
- project_id (text, indexed with tenant_id)
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
- resolved_version (text, nullable) // pinned version for reproducible resume, usually equals version_id
- tenant_id (text, indexed)
- project_id (text, nullable, indexed with session_id)
- session_id (text, nullable)
- status (text)
- cancellable (bool, default true)
- commit_point_reached (bool, nullable)
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

Notes:
- For document workflows, `inputs/state/outputs` should store artifact references (for example `artifact_ref`) instead of duplicating large inline binary payloads.
- `state_exclude_paths` and `output_include_paths` apply projection to persisted/returned payload shape.
- Projection settings are run-scoped metadata and do not require dedicated columns in the initial additive rollout.

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

### capabilities
Versioned capability registry for explicit workflow-step pinning.
- id (text, pk)
- tenant_id (text, indexed)
- capability_id (text)
- version (text)
- node_type (text)
- contract (jsonb) // inputs, outputs, constraints, timeout_s, retry_policy, error_codes
- created_at (timestamptz)

Unique: (tenant_id, capability_id, version)

### run_ledger
Immutable execution ledger derived from runtime transitions.
- id (text, pk)
- tenant_id (text, indexed)
- run_id (text, indexed)
- workflow_id (text)
- version_id (text)
- step_id (text, nullable)
- capability_id (text, nullable)
- capability_version (text, nullable)
- status (text)
- event_type (text)
- decision (jsonb, nullable)
- artifacts (jsonb array)
- payload (jsonb)
- created_at (timestamptz)

### workflow_handoffs
Atomic handoff package intake records with replay metadata.
- id (text, pk)
- tenant_id (text, indexed)
- workflow_id (text)
- version_id (text, nullable)
- context (jsonb)
- constraints (jsonb)
- expected_result (jsonb)
- acceptance_checks (jsonb array)
- replay_mode (text) // none | deterministic
- idempotency_key (text, nullable)
- run_id (text, nullable)
- status (text)
- metadata (jsonb)
- created_at, updated_at (timestamptz)

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

## ChatKit persistence tables (MVP)

### chatkit_threads
- tenant_id (text)
- id (text)
- seq (bigserial)
- title (text, nullable)
- status (jsonb)
- metadata (jsonb)
- created_at, updated_at (timestamptz)

PK: (tenant_id, id)

### chatkit_items
- tenant_id (text)
- id (text)
- thread_id (text, fk -> chatkit_threads.(tenant_id, id))
- seq (bigserial)
- type (text)
- item (jsonb)
- created_at (timestamptz)

PK: (tenant_id, id)

### chatkit_attachments
- tenant_id (text)
- id (text)
- thread_id (text, nullable, fk -> chatkit_threads.(tenant_id, id))
- attachment (jsonb)
- created_at (timestamptz)

PK: (tenant_id, id)

## Project orchestration tables (MVP)

`project_id` is unique only within tenant scope (`tenant_id + project_id`).

### projects
Project-level routing scope for orchestrated chat entry.
- tenant_id (text)
- project_id (text)
- project_name (text, not null) // human-readable display name
- default_orchestrator_id (text, nullable)
- settings (jsonb) // per-project thresholds, limits, feature flags
- created_at, updated_at (timestamptz)

PK: (tenant_id, project_id)

### orchestrator_configs
Per-project orchestrator configurations.
- tenant_id (text)
- project_id (text, fk -> projects.(tenant_id, project_id))
- orchestrator_id (text)
- name (text)
- routing_policy (jsonb) // confidence_threshold, switch_margin, max_disambiguation_turns, top_k_candidates
- fallback_workflow_id (text, nullable)
- prompt_profile (text, nullable)
- created_at, updated_at (timestamptz)

PK: (tenant_id, project_id, orchestrator_id)

### workflow_definitions
Routing index metadata per project workflow.
- tenant_id (text)
- project_id (text, fk -> projects.(tenant_id, project_id))
- workflow_id (text, fk -> workflows.id)
- name (text)
- description (text)
- tags (text[])
- examples (text[])
- active (bool)
- is_fallback (bool)
- created_at, updated_at (timestamptz)

PK: (tenant_id, project_id, workflow_id)

### orchestrator_session_state
Current orchestration state per project/session.
- tenant_id (text)
- project_id (text, fk -> projects.(tenant_id, project_id))
- session_id (text)
- orchestrator_id (text, nullable)
- active_run_id (text, nullable)
- pending_disambiguation (bool)
- pending_question (text, nullable)
- pending_options (jsonb array)
- disambiguation_turns (int)
- last_user_message_id (text, nullable)
- created_at, updated_at (timestamptz)

PK: (tenant_id, project_id, session_id)

### orchestrator_context
Unified persisted context key/value store for orchestrator/chat scopes.
- tenant_id (text)
- project_id (text, not null) // project scope; use empty string when scope is not project-bound
- scope_type (text) // `session` | `thread`
- scope_id (text) // `session_id` or `thread_id`
- key (text)
- value (jsonb)
- created_at, updated_at (timestamptz)

PK: (tenant_id, project_id, scope_type, scope_id, key)

### workflow_stack_entries
Session run stack history for diagnostics and switching trace.
- id (text, pk)
- tenant_id (text)
- project_id (text, fk -> projects.(tenant_id, project_id))
- session_id (text)
- run_id (text)
- stack_index (int)
- transition_reason (text)
- from_run_id (text, nullable)
- created_at (timestamptz)

Unique: (tenant_id, project_id, session_id, stack_index)

### orchestration_decisions
Structured orchestration decision log for every inbound message.
- decision_id (text, pk)
- tenant_id (text)
- project_id (text, fk -> projects.(tenant_id, project_id))
- orchestrator_id (text, nullable)
- session_id (text)
- message_id (text)
- mode (text) // direct | orchestrated
- active_run_id (text, nullable)
- context_ref (jsonb) // summary/version refs used for routing
- candidates (jsonb array) // workflow_id, score, reason_codes
- chosen_action (text)
- chosen_workflow_id (text, nullable)
- confidence (double precision)
- latency_ms (int)
- model_id (text, nullable)
- error_code (text, nullable)
- created_at (timestamptz)

## Workflow reliability tables

### capabilities
Versioned capability registry for explicit workflow-step pinning.
- id (text, pk)
- tenant_id (text)
- capability_id (text)
- version (text)
- node_type (text)
- contract (jsonb)
- created_at (timestamptz)

Unique: (tenant_id, capability_id, version)

### run_ledger
Immutable execution ledger derived from runtime transitions.
- id (text, pk)
- tenant_id (text)
- run_id (text)
- workflow_id (text)
- version_id (text)
- step_id (text, nullable)
- capability_id (text, nullable)
- capability_version (text, nullable)
- status (text)
- event_type (text)
- decision (jsonb, nullable)
- artifacts (jsonb array)
- payload (jsonb)
- created_at (timestamptz)

### workflow_handoffs
Atomic handoff package intake records with replay metadata.
- id (text, pk)
- tenant_id (text)
- workflow_id (text)
- version_id (text, nullable)
- run_id (text, nullable)
- replay_mode (text) // none | deterministic
- status (text) // RECEIVED | STARTED | REPLAYED | FAILED
- context (jsonb)
- constraints (jsonb)
- expected_result (jsonb)
- acceptance_checks (jsonb array)
- metadata (jsonb)
- idempotency_key (text, nullable)
- created_at, updated_at (timestamptz)

## Indexing notes
- workflows: index by (tenant_id, project_id, updated_at).
- runs: index by (tenant_id, workflow_id, status, created_at).
- node_runs: index by (run_id, status).
- events: index by (tenant_id, run_id, created_at).
- orchestrator_context: index by (tenant_id, project_id, scope_type, scope_id, updated_at).
- capabilities: index by (tenant_id, capability_id, created_at).
- run_ledger: index by (tenant_id, run_id, created_at).
- workflow_handoffs: index by (tenant_id, workflow_id, created_at).
- webhook_deliveries: index by (status, next_retry_at).
- idempotency_keys: index by (tenant_id, idempotency_key, scope), (expires_at).
- capabilities: index by (tenant_id, capability_id, created_at).
- run_ledger: index by (tenant_id, run_id, created_at).
- workflow_handoffs: index by (tenant_id, workflow_id, created_at).

## Headless testing
All UI/E2E tests run headless by default in CI. No GUI dependencies are assumed for automated pipelines.
