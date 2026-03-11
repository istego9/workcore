# Changelog

All notable public API changes in this repository must be documented in this file.

The format follows a simple date-based log.

## 2026-03-11

### API diff vs previous version
- Previous API version: `0.24.6`
- Current API version: `0.24.7`
- Compatibility: additive (typed error fields and negotiation endpoint added without removing existing error envelope keys)

### Added
- New public read-only negotiation endpoint:
  - `GET /integration-capabilities`
- New shared OpenAPI schemas:
  - `PlatformError`
  - `PlatformErrorEnvelope`
- New manifest field for onboarding/discovery:
  - `integration_manifest.integration_capabilities_url` (in `/agent-integration-kit.json` and onboarding ZIP `integration_manifest.json`)
- New ADR:
  - `docs/adr/ADR-0014-typed-error-contract-and-capability-negotiation.md`

### Changed
- `ErrorEnvelope` now aligns to the additive platform-typed error contract while preserving existing `error.code`, `error.message`, and `correlation_id` compatibility.
- `OrchestratorActionError` now reuses the shared platform error structure and keeps required `action`.
- Public integration surfaces now emit additive typed error fields (`category`, `retryable`, `retry_after_s`, `bad_fields`, `unsupported_feature`, `docs_ref`, nested `correlation_id`) on failures:
  - `POST /chat`
  - `POST /chatkit`
  - `POST /orchestrator/messages`
  - `POST /workflows/{workflow_id}/runs`
  - `POST /handoff/packages`
- Public drift sentinel now enforces negotiation endpoint presence and shared error-contract alignment across OpenAPI/docs/runtime references.

### Deprecated
- None.

### Removed
- None.

## 2026-03-11

### API diff vs previous version
- Previous API version: `0.24.5`
- Current API version: `0.24.6`
- Compatibility: additive (existing onboarding endpoints preserved; host policy is now explicit in manifest/doctor contracts)

### Added
- `integration_manifest.host_policy` in onboarding bundle surfaces (`/agent-integration-kit.json` and onboarding ZIP `integration_manifest.json`).
- Partner-aware doctor evaluation (`/agent-integration-test.json`) supports explicit host policy validation via optional `partner_id` query.

### Changed
- Replaced brittle partner marker host normalization with explicit partner host policy mapping.
- Enforced pinned host policy for `partner_id=epam_future-insurance`:
  - canonical base URL: `https://api.runwcr.com`
  - allowed domains: `["api.runwcr.com"]`
- Integration doctor host policy check now fails on pinned-host mismatch and supports partner-aware evaluation with `partner_id` query parameter.
- Integration guide wording updated: removed primary/alias host framing and switched to policy-driven host canon.

### Deprecated
- None.

### Removed
- Implicit host normalization based on `epam` substring markers.

## 2026-03-11

### API diff vs previous version
- Previous API version: `0.24.4`
- Current API version: `0.24.5`
- Compatibility: additive (existing onboarding endpoints preserved; machine-readable manifest + doctor checks extended)

### Added
- Canonical integration manifest fields for partner onboarding surfaces:
  - `api_base_url`
  - `chat_api_url`
  - `deprecated_chat_alias_url` + deprecation metadata
  - `auth_profile` (`oauth_client_credentials`)
  - required/optional headers
  - `project_scope`
  - `secret_expiry` warning metadata
- Doctor-style integration checks for `/agent-integration-test.json`:
  - `status` (`PASS|WARN|FAIL`)
  - `severity`, `code`, `title`, `message`
  - `observed`, `expected`, `remediation`, `docs_ref`
- Internal onboarding ZIP artifacts:
  - `integration_manifest.json`
  - `curl_examples/check_auth.sh`
  - `curl_examples/check_project_scope.sh`
  - `curl_examples/check_chat.sh`

### Changed
- `/agent-integration-kit.json` now includes a normalized `integration_manifest` reused by onboarding package generation.
- `/agent-integration-test.json` now acts as an integration doctor and validates canonical `/chat` usage and `/chatkit` deprecation posture.
- `/internal/partner-access` now surfaces canonical host/auth/chat summary and secret rotation warnings before bundle download.
- Public contract drift sentinel now verifies onboarding/doctor surfaces stay aligned with canonical chat contract and deprecation lifecycle.
- Full-stack acceptance env handling now uses canonical `E2E_CHAT_API_URL` only.

### Deprecated
- None.

### Removed
- Deprecated fallback env alias `E2E_CHATKIT_API_URL` from full-stack acceptance/e2e environment resolution.

## 2026-03-11

### API diff vs previous version
- Previous API version: `0.24.3`
- Current API version: `0.24.4`
- Compatibility: additive (public chat thread creation is now project-centric by default while explicit workflow clients remain supported)

### Added
- Public chat project-scope resolution for `threads.create`:
  - `metadata.project_id`
  - `X-Project-Id`
  - per-project setting `projects.settings.default_chat_workflow_id`
- Stable typed chat errors:
  - `CHAT_PROJECT_SCOPE_REQUIRED`
  - `CHAT_DEFAULT_WORKFLOW_NOT_CONFIGURED`
  - `CHAT_DEFAULT_WORKFLOW_NOT_FOUND`
- Thread metadata / logs now persist resolved project/workflow scope and `chat_resolution_mode`.

### Changed
- `POST /chat` now resolves new threads in this order:
  - `metadata.workflow_id`
  - `metadata.project_id`
  - `X-Project-Id`
- `POST /chatkit` inherits the same success/error behavior as `POST /chat` during the deprecation window.
- Project update contract now supports additive settings updates for `default_chat_workflow_id`.

### Deprecated
- None.

### Removed
- None.

## 2026-03-11

### API diff vs previous version
- Previous API version: `0.24.2`
- Current API version: `0.24.3`
- Compatibility: additive (deprecated `/chatkit` compatibility alias restored during transition window; canonical endpoint remains `/chat`)

### Added
- Public OpenAPI path:
  - `POST /chatkit` as deprecated compatibility alias for `POST /chat`
- Deprecated alias lifecycle headers:
  - `Deprecation: true`
  - `Sunset: Sat, 04 Apr 2026 00:00:00 GMT`
- Explicit post-sunset behavior in contract/runtime:
  - `POST /chatkit` returns `410 Gone` starting `2026-04-04T00:00:00Z`

### Changed
- Runtime parity during transition window:
  - `POST /chat` and `POST /chatkit` now produce the same payload/SSE semantics
- Public docs now describe one canonical chat path (`/chat`) plus compatibility alias lifecycle (`/chatkit` -> `410`)

### Deprecated
- `POST /chatkit` remains deprecated and must be migrated to `POST /chat` before sunset.

### Removed
- None.

## 2026-03-09

### API diff vs previous version
- Previous API version: `0.24.1`
- Current API version: `0.24.2`
- Compatibility: additive/non-breaking (internal onboarding defaults now enforce EPAM-specific host policy)

### Added
- Internal onboarding host policy for EPAM partner requests:
  - generated onboarding artifacts use only `https://api.runwcr.com`
  - `allowed_domains` are normalized to `api.runwcr.com`

### Changed
- Internal self-service onboarding docs and OpenAPI now describe EPAM-specific base URL normalization for generated ZIP artifacts.

### Deprecated
- None.

### Removed
- None.

## 2026-03-05

### API diff vs previous version
- Previous API version: `0.24.0`
- Current API version: `0.24.1`
- Compatibility: additive (internal self-service onboarding now supports auto-generated IDs)

### Added
- Optional auto-generation behavior for internal self-service onboarding request:
  - `partner_id` can be omitted and is generated from `display_name`
  - `tenant_id_pinned` can be omitted and defaults to resolved `partner_id`

### Changed
- Internal operator guidance now treats `display_name` as the minimal required onboarding input.

### Deprecated
- None.

### Removed
- None.

## 2026-03-05

### API diff vs previous version
- Previous API version: `0.23.0`
- Current API version: `0.24.0`
- Compatibility: additive (new internal partner onboarding self-service endpoints)

### Added
- Internal operator endpoints:
  - `GET /internal/partner-access`
  - `POST /internal/partner-access/onboard-package`
- New request schema:
  - `PartnerSelfServiceOnboardRequest`
- Internal portal auth scheme in OpenAPI:
  - `entraEasyAuthPrincipal` (`X-MS-CLIENT-PRINCIPAL`)

### Changed
- API reference now documents internal onboarding self-service flow and generated ZIP artifacts.

### Deprecated
- None.

### Removed
- None.

## 2026-03-05

### API diff vs previous version
- Previous API version: `0.22.0`
- Current API version: `0.23.0`
- Compatibility: additive (auth model for external clients moved to APIM + Entra OAuth2 without endpoint/payload changes)

### Added
- OAuth2 client_credentials guidance for external integrations:
  - Entra token endpoint
  - `scope=api://workcore-partner-api/.default`
- APIM gateway deployment and partner lifecycle automation scripts:
  - `deploy_apim.sh`
  - `apim_partner_onboard.sh`
  - `apim_partner_rotate_secret.sh`
  - `apim_partner_revoke.sh`

### Changed
- OpenAPI global security scheme now documents OAuth2 client_credentials instead of static bearer token provisioning.
- API reference and integration guide now document partner authentication via APIM + Entra OAuth tokens.
- Azure deployment architecture now includes APIM as mandatory API gateway in front of runtime services.

### Deprecated
- Direct external distribution of internal runtime bearer secrets (`WORKCORE_API_AUTH_TOKEN`, `CHATKIT_AUTH_TOKEN`).

### Removed
- External auth guidance based on reading bearer secrets directly from Key Vault.

## 2026-03-04

### API diff vs previous version
- Previous API version: `0.21.0`
- Current API version: `0.22.0`
- Compatibility: breaking (`POST /chatkit` removed from public contract; canonical chat endpoint is now `POST /chat`)

### Added
- Public ChatKit endpoint path in contract and integration docs:
  - `POST /chat`
- Dual production auth profile documentation for chat integrations:
  - single bearer (shared token for `/orchestrator/*` and `/chat`)
  - split bearer (independent tokens for `/orchestrator/*` and `/chat`)

### Changed
- OpenAPI path migrated from `/chatkit` to `/chat` without payload shape changes.
- Integration kit examples and API reference examples now use `"$BASE_URL/chat"`.
- Edge/path routing guidance now standardizes single API host + path split:
  - `/chat` and `/chat/*` -> ChatKit transport
  - `/orchestrator/*` and other API paths -> orchestrator API

### Deprecated
- None.

### Removed
- Public endpoint path `POST /chatkit` from OpenAPI contract and integration guides.

## 2026-03-04

### API diff vs previous version
- Previous API version: `0.20.0`
- Current API version: `0.21.0`
- Compatibility: additive (run and ledger responses now include backward-compatible diagnostics aliases)

### Added
- `Run.error` (nullable string): run-level failure message mirrored from failed node diagnostics.
- `Run.last_error` (nullable string): alias of `Run.error` for legacy clients.
- `Run.failed_node_id` (nullable string): selected node id source for run-level diagnostics.
- `Run.node_states` (array): backward-compatible alias of `Run.node_runs`.
- `RunLedgerEntry.node_id` (nullable string): backward-compatible alias of `step_id`.

### Changed
- Failed runs now expose node-derived diagnostics at run top-level for clients that do not parse `node_runs`.
- Ledger responses now expose both `step_id` and `node_id` with identical value for node-scoped events.

### Deprecated
- None.

### Removed
- None.

## 2026-03-02

### API diff vs previous version
- Previous API version: `0.19.0`
- Current API version: `0.20.0`
- Compatibility: additive (Chat fork widget extension schema now supports full Nivo chart type registry via `chart_type` + `nivo_props`)

### Added
- `chatkit-widget-extension` schema now documents `Chart.chart_type` with full Nivo chart registry:
  - `bar`, `line`, `pie`, `area-bump`, `bump`
  - `boxplot`, `bullet`, `calendar`, `chord`, `circle-packing`
  - `funnel`, `geo`, `heatmap`, `icicle`, `marimekko`
  - `network`, `parallel-coordinates`, `polar-bar`, `radar`, `radial-bar`
  - `sankey`, `scatterplot`, `stream`, `sunburst`, `swarmplot`
  - `tree`, `treemap`, `waffle`
- `chatkit-widget-extension` schema now documents `Chart.nivo_props` for pass-through renderer configuration.

### Changed
- `chatkit-widget-extension` `Chart.data` contract now allows both object and array payloads (for hierarchy/network/chart-specific shapes).
- `chatkit-widget-extension` no longer requires `data` + `series` for all charts; required fields are now chart-type-specific.

### Deprecated
- None.

### Removed
- None.

## 2026-02-26

### API diff vs previous version
- Previous API version: `0.18.0`
- Current API version: `0.19.0`
- Compatibility: additive (`/chatkit` now documents optional `input.transcribe` non-stream request type)

### Added
- New additive ChatKit request contract:
  - `type: input.transcribe`
  - `params.audio_base64`
  - `params.mime_type`
- New ChatKit response schema:
  - `ChatKitTranscriptionResult` (`{ text: string }`)
- New JSON schema endpoints:
  - `/schemas/chatkit-input-transcribe-request.schema.json`
  - `/schemas/chatkit-widget-extension.schema.json`

### Changed
- `/chatkit` endpoint documentation now explicitly covers mixed response mode:
  - SSE stream for interactive `threads.*` operations
  - JSON response for `input.transcribe`
- `ChatKitRequest` union now includes transcribe request shape.

### Deprecated
- None.

### Removed
- None.

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
