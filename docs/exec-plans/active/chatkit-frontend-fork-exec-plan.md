# Execution Plan: Chat Frontend Fork (Variant D)

## Metadata
- Date: 2026-02-26
- Owner: Platform/Builder team
- Task classification: A + E (+ B/C due additive API and stream semantics docs)
- Related issue/spec: chat frontend fork for custom objects, STT dictation, and theming

## Goal and scope
- Goal:
  - Build a forked chat frontend while preserving compatibility with existing `/chatkit` behavior.
- In scope:
  - Fork frontend shell (`chat-fork.html` + React app).
  - Widget parity for current interrupt widgets and actions.
  - Custom object rendering MVP: charts + tables.
  - STT dictation flow (`input.transcribe`).
  - Feature-flag rollout with fallback to legacy ChatKit UI.
- Out of scope:
  - Continuous full voice mode (duplex call UX).
  - Backend ChatKit runtime fork.
  - Full white-label tenant-level branding.

## Mandatory action items (required for A-E)
1. Goal and scope
   - This file is the tracked execution artifact for scope and delivery boundaries.
2. Spec files to update (exact paths)
   - `docs/api/openapi.yaml`
   - `docs/api/schemas/chatkit-input-transcribe-request.schema.json` (new)
   - `docs/api/schemas/chatkit-widget-extension.schema.json` (new)
   - `docs/architecture/chatkit.md`
   - `docs/architecture/overview.md`
   - `docs/adr/ADR-0010-chat-frontend-fork.md` (new)
   - `CHANGELOG.md`
3. Compatibility strategy (additive vs breaking)
   - Additive only. Existing `threads.create`, `threads.add_user_message`, `threads.custom_action`, widget action aliases, and interrupt behavior remain valid.
4. Implementation files
   - Frontend:
     - `apps/builder/chat-fork.html` (new)
     - `apps/builder/src/chat-fork/main.tsx` (new)
     - `apps/builder/src/chat-fork/App.tsx` (new)
     - `apps/builder/src/chat-fork/protocol/types.ts` (new)
     - `apps/builder/src/chat-fork/protocol/sse.ts` (new)
     - `apps/builder/src/chat-fork/api/chatkit-client.ts` (new)
     - `apps/builder/src/chat-fork/state/thread-store.ts` (new)
     - `apps/builder/src/chat-fork/widgets/WidgetRenderer.tsx` (new)
     - `apps/builder/src/chat-fork/widgets/extensions/NivoChart.tsx` (new)
     - `apps/builder/src/chat-fork/widgets/extensions/DataTable.tsx` (new)
     - `apps/builder/src/chat-fork/stt/useSttRecorder.ts` (new)
     - `apps/builder/src/chat-fork/theme/tokens.ts` (new)
     - `apps/builder/src/App.tsx` (feature-flag + fallback URL selection)
     - `apps/builder/package.json` (+ lockfile) for chart dependencies
   - Backend:
     - `apps/orchestrator/chatkit/server.py` (`transcribe()` override)
     - `apps/orchestrator/chatkit/service.py` (wire STT transcriber)
     - `apps/orchestrator/chatkit/config.py` (STT env config)
5. Tests (unit/integration/contract/e2e)
   - Frontend unit: SSE parsing, widget rendering parity, chart/table extension rendering, STT hook payload behavior.
   - Backend unit/integration: `input.transcribe` success/failure and validation (mime/type/size), tenant/auth invariants.
   - E2E: fork page baseline render, URL/fallback switching, action/interrupt happy path, STT composer insert path.
6. Observability/security impacts
   - Metrics:
     - `chat_fork_stream_error_total`
     - `chat_fork_widget_render_error_total`
     - `chat_fork_stt_request_total`
     - `chat_fork_stt_latency_ms`
     - `chat_fork_stt_failure_total`
   - Security:
     - mime whitelist (`audio/webm`, `audio/ogg`, `audio/mp4`).
     - max input size and duration guardrails.
     - never log `audio_base64` payload.
7. Rollout/rollback notes
   - Feature flag: `VITE_CHAT_FRONTEND_MODE=chatkit|fork` (default `chatkit`).
   - Query override for testing: `chat_ui=fork`.
   - Rollout: internal -> selected tenants -> full.
   - Rollback: set flag to `chatkit`; no DB migration rollback required.
8. Outstanding TODOs/questions
   - Voice mode Phase 2 boundary (half-duplex vs full-duplex).
   - Table interaction depth in v1 (read-only is default).
   - STT latency/accuracy SLA baseline after first telemetry pass.

## Implementation plan (iterations)
1. Iteration 0 (Spec-first)
   - Update OpenAPI/schemas/architecture/ADR/changelog.
2. Iteration 1 (Fork shell)
   - Build chat-fork app with thread timeline, composer, stream handling.
3. Iteration 2 (Widget parity)
   - Render current interrupt widgets and action dispatch semantics.
4. Iteration 3 (Custom objects)
   - Add chart + table extensions with graceful fallback.
5. Iteration 4 (STT)
   - Implement browser recorder + `input.transcribe`; implement backend transcriber.
6. Iteration 5 (Flag/theming/hardening)
   - Feature flag integration, design tokens/theme packs, guardrails.
7. Iteration 6 (Validation/release)
   - Run full checks and finalize rollout/rollback docs.

## Validation plan
- Commands to run:
  - `./scripts/archctl_validate.sh`
  - `./.venv/bin/python -m pytest apps/orchestrator/tests`
  - `cd apps/builder && npm run test:unit`
  - `cd apps/builder && npm run test:e2e`
  - `./scripts/dev_check.sh`
- Expected outcomes:
  - No contract regressions for existing ChatKit flows.
  - Added tests cover transcribe and fork renderer paths.
- Evidence artifacts (logs/screenshots/reports):
  - Test command outputs + Playwright artifacts for fork page.

## Rollout and rollback
- Rollout steps:
  - Deploy with `VITE_CHAT_FRONTEND_MODE=chatkit`.
  - Enable for internal tenants with `chat_ui=fork`.
  - Enable progressively via env toggle in each environment.
- Rollback trigger:
  - Elevated stream/render/STT failure metrics or user-facing blocking bugs.
- Rollback steps:
  - Switch mode back to `chatkit`; keep backend transcribe additive endpoints available.

## Decision log
- 2026-02-26: Strategy fixed to additive API, STT dictation MVP, fork rollout via feature flag + fallback.

## Post-completion notes
- What changed from the original plan:
  - TBD after implementation.
- Follow-up tasks:
  - Voice mode Phase 2 evaluation.
