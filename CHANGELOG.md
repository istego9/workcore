# Changelog

All notable public API changes in this repository must be documented in this file.

The format follows a simple date-based log.

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
