# ADR-0010: Frontend ChatKit Fork Boundary and Compatibility Strategy

Date: 2026-02-26
Status: Proposed

## Context
Current chat UX relies on embedded `openai-chatkit` frontend. Product requirements require:
- richer custom in-chat objects (chart/table-heavy flows),
- more flexible styling/theming,
- speech-to-text dictation support,
- preserving current widget/action behavior used by workflow interrupts.

Full backend/protocol fork is high-cost and unnecessary for MVP.

## Decision
Adopt frontend-only fork strategy (Variant D) with strict compatibility boundaries:

1. Keep backend `/chatkit` as source of truth.
- Existing interactive operations remain unchanged:
  - `threads.create`
  - `threads.add_user_message`
  - `threads.custom_action`
- Additive non-stream operation:
  - `input.transcribe` -> `{ "text": "<transcript>" }`

2. Introduce optional fork frontend shell behind feature flag.
- Legacy path remains available as default.
- Fork shell reuses the same request/stream contracts and widget action payload model.

3. Preserve widget parity first, extend second.
- Preserve current interrupt widget semantics (`approval`, `interaction`) and action dedupe behavior.
- Extend rendering layer for custom components:
  - Chart mapped to Nivo renderer adapters.
  - DataTable extension component (read-only MVP).
- Unknown widget component types must fail gracefully with a safe fallback.

4. Ship STT as dictation-only MVP.
- Browser records short audio snippets.
- Frontend sends `input.transcribe`.
- Transcript is inserted into composer; user manually sends message.
- Continuous voice mode is deferred to Phase 2.

## Compatibility strategy
- Additive only.
- No breaking changes to existing `threads.*` contracts or interrupt widget handling.
- Feature flag rollback to legacy frontend without backend migration rollback.

## Consequences
- Faster iteration on frontend capabilities without immediate protocol fork.
- Added frontend ownership burden (renderer/state/transport) and extra test surface.
- Controlled operational risk due to fallback mode and additive API evolution.

## Risks and mitigations
- Risk: fork frontend diverges from backend stream semantics.
  - Mitigation: contract tests for stream/event handling and widget actions.
- Risk: transcription adds abuse/latency/security concerns.
  - Mitigation: mime/size limits, non-sensitive logging policy, metrics for latency/failures.
- Risk: unknown extension component payloads break UI.
  - Mitigation: robust fallback renderer with non-fatal behavior.

## Follow-up
- Evaluate Phase 2 voice mode boundary (half-duplex vs full-duplex).
- Expand DataTable interactions (sorting/filtering/pagination) post-MVP.
- Track STT quality and latency SLOs from production telemetry.
