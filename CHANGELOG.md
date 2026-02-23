# Changelog

All notable public API changes in this repository must be documented in this file.

The format follows a simple date-based log.

## 2026-02-20

### API diff vs previous version
- Previous API version: `0.17.0`
- Current API version: `0.18.0`
- Compatibility: additive (`/orchestrator/messages` now documents optional custom-action envelope fields)

### Added
- `OrchestratorUserMessage` now documents optional `type`:
  - `threads.add_user_message`
  - `threads.custom_action`
- `OrchestratorUserMessage` now documents optional `payload` for custom-action messages.
- New schema: `OrchestratorCustomActionPayload`.
- New OpenAPI request examples for `POST /orchestrator/messages`:
  - standard user message
  - `threads.custom_action` with structured payload

### Changed
- `POST /orchestrator/messages` contract now explicitly documents how custom-action fields are materialized for runtime input mapping:
  - `message.text` -> `inputs.action_type`
  - normalized payload fields -> flattened `inputs.*`

### Deprecated
- None.

### Removed
- None.

## 2026-02-20

### API diff vs previous version
- Previous API version: `0.16.0`
- Current API version: `0.17.0`
- Compatibility: changed (context API validation status normalized to 422)

### Added
- None.

### Changed
- Context API (`POST /orchestrator/context/get|set|unset`) now documents validation errors consistently as HTTP `422`.
- Removed ambiguous `400` validation response entries for context endpoints from OpenAPI.

### Deprecated
- None.

### Removed
- None.

## 2026-02-20

### API diff vs previous version
- Previous API version: `0.15.0`
- Current API version: `0.16.0`
- Compatibility: additive (new offline routing replay/eval endpoint and schemas)

### Added
- New endpoint:
  - `POST /orchestrator/eval/replay`
- New schemas:
  - `OrchestratorEvalReplayCase`
  - `OrchestratorEvalReplayRequest`
  - `OrchestratorEvalReplayMetrics`
  - `OrchestratorEvalReplayCaseResult`
  - `OrchestratorEvalReplayResponse`

### Changed
- Agent integration kit now includes orchestrator replay/eval URL in required integration URLs.
- Integration test openapi path checks now require `/orchestrator/eval/replay`.

### Deprecated
- None.

### Removed
- None.

## 2026-02-20

### API diff vs previous version
- Previous API version: `0.14.0`
- Current API version: `0.15.0`
- Compatibility: additive (routing policy contract expanded with switch-control and anti-flip fields)

### Added
- New schema: `RoutingPolicy`
- `OrchestratorConfigUpsertRequest.routing_policy` now references `RoutingPolicy`.
- `OrchestratorConfig.routing_policy` now references `RoutingPolicy`.
- New routing policy fields:
  - `sticky`
  - `allow_switch`
  - `explicit_switch_only`
  - `cooldown_seconds`
  - `hysteresis_margin`

### Changed
- Orchestrator policy documentation now explicitly describes anti-flip/hysteresis behavior.

### Deprecated
- None.

### Removed
- None.

## 2026-02-20

### API diff vs previous version
- Previous API version: `0.13.0`
- Current API version: `0.14.0`
- Compatibility: additive (orchestrator response now includes standardized route/action error contract)

### Added
- New schema: `OrchestratorActionError`
- New response field: `OrchestratorMessageResponse.action_error`

### Changed
- Orchestrator route/action failures that do not raise transport-level HTTP errors now expose normalized error metadata:
  - `code`
  - `message`
  - `retryable`
  - `category`
  - `action`

### Deprecated
- None.

### Removed
- None.

## 2026-02-20

### API diff vs previous version
- Previous API version: `0.12.0`
- Current API version: `0.13.0`
- Compatibility: additive (`/orchestrator/messages` response extended with decision trace fields)

### Added
- New response schema: `OrchestratorDecisionTraceCandidate`
- New response schema: `OrchestratorDecisionTrace`
- `OrchestratorMessageResponse.decision_trace` with:
  - workflow candidates and scores
  - selected action/workflow
  - reason codes and selection reason
  - switch details (`switch_from_workflow_id`, `switch_to_workflow_id`, `switch_reason`)

### Changed
- API reference now documents decision-trace payload for orchestrator routing transparency.

### Deprecated
- None.

### Removed
- None.

## 2026-02-20

### API diff vs previous version
- Previous API version: `0.11.0`
- Current API version: `0.12.0`
- Compatibility: additive (ChatKit custom action payload contract clarified and validated; existing payload keys remain supported)

### Added
- `ChatKitActionPayload` now documents optional projection control fields:
  - `state_exclude_paths`
  - `output_include_paths`

### Changed
- `threads.custom_action` submit payload normalization is now explicit in API contract:
  - extraction priority across `input` / `form` / `form_data` / `fields`
  - flattening of wrapper keys into a single runtime input object
  - scalar string typing (`true/false`, numeric literals, `null`)
  - `documents` passthrough behavior
- Projection controls in action payload are validated with the same path rules as run start payload.

### Deprecated
- None.

### Removed
- None.

## 2026-02-20

### API diff vs previous version
- Previous API version: `0.10.0`
- Current API version: `0.11.0`
- Compatibility: additive (new context endpoints and workflow node contract extension; existing routes remain supported)

### Added
- Orchestrator context endpoints:
  - `POST /orchestrator/context/get`
  - `POST /orchestrator/context/set`
  - `POST /orchestrator/context/unset`
- New API schemas:
  - `OrchestratorContextScope`
  - `OrchestratorContextGetRequest`
  - `OrchestratorContextSetRequest`
  - `OrchestratorContextUnsetRequest`
  - `OrchestratorContextResponse`
- Workflow node contract extension for `integration_http` configuration fields.

### Changed
- `ChatKitAction` now supports canonical action field `action_type` with backward-compatible alias field `type`.
- ChatKit custom action examples now use canonical `action_type`.

### Deprecated
- None.

### Removed
- None.

## 2026-02-19

### API diff vs previous version
- Previous API version: `0.9.0`
- Current API version: `0.10.0`
- Compatibility: additive (project management endpoints extended without breaking existing contracts)

### Added
- Project management endpoints:
  - `PATCH /projects/{project_id}` updates project metadata (`project_name`).
  - `DELETE /projects/{project_id}` deletes a project when it has no workflows.
- New API schema:
  - `ProjectUpdateRequest`

### Changed
- API reference now documents project update/delete flows for admin Explore UX.
- `DELETE /projects/{project_id}` now returns `409` when a project still contains workflows.

### Deprecated
- None.

### Removed
- None.

## 2026-02-18

### API diff vs previous version
- Previous API version: `0.8.0`
- Current API version: `0.9.0`
- Compatibility: additive (new artifact read endpoint and error codes; no-inline defaults apply only to newly published workflow versions)

### Added
- Artifact read endpoint:
  - `GET /artifacts/{artifact_ref}`
- New API schema:
  - `ArtifactReadResponse`
- New error codes:
  - `artifact.not_found`
  - `artifact.access_denied`
  - `artifact.expired`
  - `projection.path_invalid`

### Changed
- `POST /workflows/{workflow_id}/runs` now returns `projection.path_invalid` for invalid projection path syntax.
- Newly published workflow versions now apply no-inline defaults by version metadata; existing published versions preserve legacy behavior unless explicitly switched.

### Deprecated
- None.

### Removed
- None.

## 2026-02-18

### API diff vs previous version
- Previous API version: `0.7.0`
- Current API version: `0.8.0`
- Compatibility: additive (new reliability endpoints and schemas; existing flows remain supported)

### Added
- Capability Registry endpoints:
  - `POST /capabilities`
  - `GET /capabilities`
  - `GET /capabilities/{capability_id}/versions`
- Run Ledger endpoint:
  - `GET /runs/{run_id}/ledger`
- Atomic Handoff endpoints:
  - `POST /handoff/packages`
  - `POST /handoff/packages/{handoff_id}/replay`
- New API schemas:
  - `CapabilityContract`
  - `CapabilityCreateRequest`
  - `Capability`
  - `PaginatedCapabilities`
  - `RunLedgerEntry`
  - `PaginatedRunLedger`
  - `HandoffPackagePayload`
  - `HandoffPackageCreateRequest`
  - `HandoffPackage`

### Changed
- `WorkflowNode.config` now documents optional capability pin fields:
  - `capability_id`
  - `capability_version`
- API reference now documents capability registry, run ledger, and atomic handoff/replay flows.

### Deprecated
- None.

### Removed
- None.

## 2026-02-18

### API diff vs previous version
- Previous API version: `0.6.0`
- Current API version: `0.7.0`
- Compatibility: additive (artifact-reference and projection controls added; inline payloads remain supported for migration)

### Added
- Run request projection controls:
  - `RunCreateRequest.state_exclude_paths`
  - `RunCreateRequest.output_include_paths`
- Document input schemas for run/webhook inputs:
  - `RunInputs`
  - `RunInputDocument`
  - `RunInputDocumentPage`
  - `ProjectionPath`
- OpenAPI run-start example now includes artifact-reference document page payload and projection controls.

### Changed
- Run input contract guidance now prefers `documents[].pages[].artifact_ref` over inline binary content.
- Run/state/output payload schema descriptions now document projection-aware transport behavior.

### Deprecated
- None.

### Removed
- None.

## 2026-02-18

### API diff vs previous version
- Previous API version: `0.5.2`
- Current API version: `0.6.0`
- Compatibility: breaking (`POST /projects` now requires `project_name`)

### Added
- Project contract now includes human-readable `project_name` in `Project` response schema.

### Changed
- `POST /projects` request now requires both:
  - `project_id`
  - `project_name`
- Project creation/list responses now include `project_name`.

### Deprecated
- None.

### Removed
- None.

## 2026-02-18

### API diff vs previous version
- Previous API version: `0.5.1`
- Current API version: `0.5.2`
- Compatibility: additive (workflow draft contract extended for batch `set_state` assignments; legacy fields retained)

### Added
- Workflow draft contract now supports batch `set_state` config:
  - `set_state.config.assignments[]` with `{ target, expression }`.
- OpenAPI now documents `WorkflowSetStateAssignment` and `WorkflowNode.config.assignments`.

### Changed
- Workflow authoring/reference docs now describe `set_state` dual-mode contract:
  - legacy `target` + `expression`
  - batch `assignments[]` (executed in order)

### Deprecated
- None.

### Removed
- None.

## 2026-02-18

### API diff vs previous version
- Previous API version: `0.5.0`
- Current API version: `0.5.1`
- Compatibility: additive (new read endpoint, existing project bootstrap/write endpoints unchanged)

### Added
- Project listing endpoint:
  - `GET /projects` returns tenant-scoped `ProjectList` (`items`, `next_cursor`).

### Changed
- API reference now documents project listing for admin/project-selection flows.

### Deprecated
- None.

### Removed
- None.

## 2026-02-16

### API diff vs previous version
- Previous API version: `0.4.3`
- Current API version: `0.5.0`
- Compatibility: breaking (tenant scoping tightened for ChatKit and integration diagnostics endpoint now requires auth)

### Added
- Required tenant header parameter for strict multi-tenant ChatKit endpoint:
  - `POST /chatkit` now requires `X-Tenant-Id`.
- New reusable OpenAPI parameter:
  - `TenantIdRequired`.

### Changed
- `GET /agent-integration-logs` now follows API bearer auth policy for external integrator access.
- Project identifiers are now documented as tenant-scoped (`tenant_id + project_id`) in API and architecture docs.

### Deprecated
- None.

### Removed
- Anonymous access expectation for `GET /agent-integration-logs`.

## 2026-02-16

### API diff vs previous version
- Previous API version: `0.4.2`
- Current API version: `0.4.3`
- Compatibility: additive (project-registry bootstrap API extended without breaking existing endpoints)

### Added
- Public project-registry bootstrap endpoints:
  - `POST /projects/{project_id}/orchestrators` (upsert project orchestrator config, optional default assignment)
  - `POST /projects/{project_id}/workflow-definitions` (upsert project workflow definition routing metadata)

### Changed
- API reference workflow lifecycle now documents required project-registry bootstrap calls before orchestrator routing.

### Deprecated
- None.

### Removed
- None.

## 2026-02-16

### API diff vs previous version
- Previous API version: `0.4.1`
- Current API version: `0.4.2`
- Compatibility: additive (agent integration metadata extended without breaking fields)

### Added
- Agent integration documentation payloads now include direct project bootstrap URL:
  - `AgentIntegrationKit.urls.projects_create`
  - `AgentIntegrationCheckReport.urls.projects_create`

### Changed
- Agent integration kit/check guidance now explicitly includes `POST /projects` in required API paths and onboarding steps.

### Deprecated
- None.

### Removed
- None.

## 2026-02-16

### API diff vs previous version
- Previous API version: `0.4.0`
- Current API version: `0.4.1`
- Compatibility: additive (no breaking endpoint removals or required-field changes)

### Added
- Project management endpoint:
  - `POST /projects` creates a project in tenant scope and returns `Project`.

### Changed
- None.

### Deprecated
- None.

### Removed
- None.

## 2026-02-13

### API diff vs previous version
- Previous API version: `0.3.0`
- Current API version: `0.4.0`
- Compatibility: breaking (workflow authoring endpoints now require explicit project scope header)

### Added
- Workflow payloads now include `project_id`:
  - `Workflow`
  - `WorkflowSummary`

### Changed
- `X-Project-Id` is now required on all workflow authoring/read endpoints:
  - `GET /workflows`
  - `POST /workflows`
  - `GET /workflows/{workflow_id}`
  - `PATCH /workflows/{workflow_id}`
  - `DELETE /workflows/{workflow_id}`
  - `PUT /workflows/{workflow_id}/draft`
  - `POST /workflows/{workflow_id}/publish`
  - `POST /workflows/{workflow_id}/rollback`
  - `GET /workflows/{workflow_id}/versions`
- `POST /workflows/{workflow_id}/runs` now returns `ERR_PROJECT_ID_REQUIRED` (`422`) when project scope is missing from request header/body metadata.

### Deprecated
- None.

### Removed
- None.

### API diff vs previous version
- Previous API version: `0.2.0`
- Current API version: `0.3.0`
- Compatibility: additive (no known breaking endpoint removals)

### Added
- Orchestrator routing API:
  - `POST /orchestrator/messages`
  - `GET /orchestrator/sessions/{session_id}/stack`
- Routing decision schema endpoint:
  - `GET /schemas/routing-decision.schema.json`
- Agent integration kit updates for orchestrator/project routing links.

### Changed
- Agent integration guidance now requires `project_id` for orchestrated chat entrypoint.
