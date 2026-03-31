# RichChart v1 Action Items

Date: 2026-03-31
Task classification: B + C + E

## 1) Goal and scope
- Introduce `RichChart` as the explicit WorkCore rich widget extension for chart rendering on chat surfaces that support the custom renderer.
- Remove semantic ambiguity between stock ChatKit `Chart` and WorkCore's custom Nivo-based chart payload.
- Keep a single `/chat` transport contract and add `RichChart` as an additive extension inside the existing widget item model.
- Scope `RichChart v1` to client-only interactivity only.
- Make `RichChart` part of the general public compatibility system for WorkCore integrations, not a partner-specific behavior.
- Restore public-host contract alignment so capability discovery works consistently on every public API host.

In scope:
- Public contract wording and schema changes for `RichChart`
- Capability negotiation changes
- Reference renderer rename/migration support (`Chart` -> `RichChart`)
- Server fallback selection rules
- Public host route/policy alignment for `GET /integration-capabilities`
- Examples, docs, and rollout smoke checks

Out of scope:
- Server-backed chart interactivity
- Widget action callbacks from chart clicks
- Cross-widget synchronization
- New top-level chat endpoints
- DB schema changes

## 2) Spec files to update
- `docs/api/openapi.yaml`
- `docs/api/reference.md`
- `docs/api/schemas/chatkit-widget-extension.schema.json`
- `docs/architecture/chatkit.md`
- `docs/architecture/chatkit-rich-chart-v1.md`
- `docs/adr/ADR-0016-rich-chart-widget-extension-v1.md`
- `CHANGELOG.md`

## 3) Compatibility strategy
- Transport compatibility remains additive:
  - `POST /chat` is unchanged
  - widget delivery stays inside `thread.item.done`
- Compatibility is platform-wide:
  - the same capability model must apply across all public hosts exposing the WorkCore public chat surface
  - no partner-specific `RichChart` contract fork is allowed
- Naming migration strategy:
  - public GA payloads emit `RichChart`
  - reference renderer accepts both legacy custom `Chart` and new `RichChart` during migration
  - stock ChatKit `Chart` semantics must not be redefined
- Capability strategy:
  - server emits `RichChart` only for known-capable clients/surfaces
  - otherwise server emits fallback native widgets

## 4) Implementation files
- `apps/orchestrator/api/app.py`
- `apps/orchestrator/chatkit/server.py`
- `apps/orchestrator/chatkit/widgets.py`
- `apps/orchestrator/workflow_engine_adapter/adapter.py`
- `apps/builder/src/chat-fork/protocol/types.ts`
- `apps/builder/src/chat-fork/widgets/WidgetRenderer.tsx`
- `apps/builder/src/chat-fork/widgets/extensions/NivoChart.tsx`
- `apps/builder/src/chat-fork/api/integration-bootstrap.ts`
- `apps/builder/public/chatkit-client.js`
- `deploy/azure/scripts/deploy_frontdoor.sh`
- `deploy/azure/scripts/deploy_apim.sh`
- `scripts/check_public_contract_drift.py`

## 5) Tests
- Contract tests:
  - `GET /integration-capabilities` includes `widget_extensions.RichChart`
  - public schema/examples reference `RichChart`, not legacy custom `Chart`
- API integration tests:
  - `/chat` fallback when client capability is absent
  - `/chat` `RichChart` emission when client capability is present
  - public host route exposure for `GET /integration-capabilities`
- Builder unit tests:
  - renderer accepts `RichChart`
  - migration alias `Chart` still renders during transition
  - unsupported rich chart payloads fail safely
- E2E tests:
  - `chat-fork` renders budget donut and line chart examples
  - fallback path renders for no-capability client

## 6) Observability/security impacts
- Add metrics/logs for:
  - `RichChart` rendered
  - `RichChart` downgraded to fallback
  - unsupported chart type
  - renderer failure
- Log only metadata:
  - component type
  - spec version
  - chart type
  - capability path
  - correlation / trace ids
- Do not log full chart datasets by default.

## 7) Rollout/rollback notes
- Rollout order:
  1. public-host hotfix for `GET /integration-capabilities` on every public host
  2. publish docs/spec and capability payload changes
  3. ship renderer migration support (`Chart` + `RichChart`)
  4. enable server `RichChart` emission for known-capable clients only
  5. partner validation against canonical examples
- Rollback:
  - disable server `RichChart` emission and keep fallback
  - keep additive docs/schema in place if already published
  - retain renderer compatibility alias until a later cleanup

## 8) Outstanding TODOs/questions
- Decide exact request metadata field for client capability hint.
- Decide whether fallback preference should be `Card`, `DataTable`, image, or workflow-specific.
- Decide whether `supported_chart_types` should advertise the full registry or a production-ready subset per host.
- Decide when to remove legacy custom `Chart` acceptance from the reference renderer.

## Implementation plan (iterations)
### Iteration 1: contract alignment and deployment hotfix
- Add `/integration-capabilities` to Front Door route patterns.
- Mark `/integration-capabilities` as a public route in APIM policy.
- Add deployment smoke checks for every public API host.
- Publish spec docs and ADR.

### Iteration 2: widget contract and reference renderer migration
- Update schema from legacy custom `Chart` naming to `RichChart`.
- Add migration alias handling in the reference renderer.
- Update examples, docs, and capability negotiation payload.

### Iteration 3: server emission and fallback control
- Introduce client capability hint parsing.
- Emit `RichChart` only when support is known.
- Emit native fallback otherwise.
- Add contract/integration/E2E coverage.

## Validation plan
- Commands to run:
  - `./scripts/archctl_validate.sh`
  - `./.venv/bin/python -m pytest apps/orchestrator/tests`
  - `cd apps/builder && npm run test:unit`
  - `cd apps/builder && npm run test:e2e`
  - `./scripts/dev_check.sh`
- Expected outcomes:
  - public contract docs and runtime stay aligned
  - `RichChart` examples validate and render on `chat-fork`
  - no-capability clients receive fallback, not broken widgets
  - `GET /integration-capabilities` responds on all public hosts with the same compatibility semantics

## Rollout and rollback
- Rollout steps:
  1. deploy Front Door/APIM hotfix
  2. deploy orchestrator/docs changes
  3. verify public host matrix
  4. validate partner example payloads
  5. enable `RichChart` emission for capability-aware clients
- Rollback trigger:
  - public route regression
  - renderer failures on capability-aware surfaces
  - partner integration breakage due to fallback mismatch
- Rollback steps:
  1. disable `RichChart` emission server-side
  2. leave renderer alias support in place
  3. fall back to native `Card`/`DataTable`/image path

## Decision log
- 2026-03-31: selected custom rich widget extension path instead of redefining stock ChatKit `Chart`.
- 2026-03-31: component name fixed to `RichChart`.
- 2026-03-31: `v1` scoped to client-only interactivity.
