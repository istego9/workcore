# ChatKit Frontend Decision Matrix

Date: 2026-02-26
Owner: Product/Engineering
Task class: F (docs only, no functional changes)

## Goal and scope
Define a practical frontend strategy for chat UX evolution with focus on:
- custom in-chat objects/components (including chart-heavy scenarios),
- style/control flexibility,
- speech-to-text (STT),
- delivery speed and maintenance cost.

This artifact is analytical only. No implementation is included.

## Current-state facts (from repository)
- Chat UI is embedded via `<openai-chatkit>` in `/Users/artemgendler/Documents/workcore/apps/builder/public/chatkit.html:142` and configured through `setOptions` in `/Users/artemgendler/Documents/workcore/apps/builder/public/chatkit.html:258`.
- Builder opens ChatKit inside `iframe` using `chatkitEmbedUrl` in `/Users/artemgendler/Documents/workcore/apps/builder/src/App.tsx:3011`.
- Builder exposes `output_format=widget` and `output_widget` in inspector UI in `/Users/artemgendler/Documents/workcore/apps/builder/src/App.tsx:2338`.
- `output_widget` exists in default node config in `/Users/artemgendler/Documents/workcore/apps/builder/src/builder/graph.ts:54`, but no orchestrator runtime usage was found.
- Current server-side widget flow is interrupt-focused templates (`approval`, `interaction`) in `/Users/artemgendler/Documents/workcore/apps/orchestrator/chatkit/widgets.py:17`.
- ChatKit protocol supports transcription request `input.transcribe` in `/Users/artemgendler/Documents/workcore/.venv/lib/python3.14/site-packages/chatkit/types.py:183`.
- Base ChatKit server requires overriding `transcribe()` for STT support in `/Users/artemgendler/Documents/workcore/.venv/lib/python3.14/site-packages/chatkit/server.py:326`.
- Installed ChatKit widget types include built-in `Chart` in `/Users/artemgendler/Documents/workcore/.venv/lib/python3.14/site-packages/chatkit/widgets.py:908`.

## Decision matrix
| Option | What changes | Custom JS components in chat (e.g. Nivo) | STT | Lead time | Delivery risk | Ongoing maintenance |
|---|---|---|---|---|---|---|
| A. Stay on current ChatKit embed | Keep current `iframe` flow; only tune existing options/widgets | Low (limited to ChatKit widget model) | Medium (requires backend `transcribe()` implementation) | Short | Low | Low |
| B. Extend ChatKit-native widgets first | Use ChatKit `Chart` + richer widget templates + enable STT | Low-Medium (more flexible content, still inside ChatKit component model) | Medium-High | Short-Medium | Low-Medium | Low-Medium |
| C. Build own frontend chat shell over existing chat backend contracts | Replace UI shell; keep existing backend run/thread/action semantics | High (full React control, including Nivo/custom rendering) | High (custom mic UX + backend STT endpoint usage) | Medium | Medium | Medium-High |
| D. Full frontend fork of ChatKit | Maintain forked ChatKit frontend runtime | High | High | Medium-Long | High | High |
| E. Full fork frontend+backend ChatKit | Own full chat protocol/runtime surface | Very High | Very High | Long | Very High | Very High |

## Recommendation
Recommended path: **B -> C**, avoid immediate full fork.

- Phase 1 (fast path): maximize native ChatKit capabilities and ship STT.
  - Implement backend transcription handling in existing ChatKit server integration.
  - Expand widget templates to cover chart/table-like outputs via supported widget primitives.
  - Validate whether built-in `Chart` satisfies near-term analytics UX.
- Phase 2 (control path): if Phase 1 is insufficient for product UX, build a custom chat shell that talks to existing backend contracts.
  - Keep orchestrator/run/interrupt contracts unchanged.
  - Decouple chat presentation layer from ChatKit-specific rendering constraints.
- Fork trigger (D/E) only if both conditions hold:
  - custom shell cannot satisfy required capability or velocity,
  - team accepts long-term ownership of compatibility/security/update burden.

## Exit criteria for strategy decision
Choose C (custom shell) when at least one is true:
- Need first-class arbitrary React component rendering in timeline, not representable in current widget model.
- Need deep visual/interaction control that repeatedly conflicts with ChatKit frontend constraints.
- Need faster iteration cadence than external ChatKit release cycle.

Choose D/E (fork) only when all are true:
- C is proven insufficient in a production-like spike,
- hard blockers are recurring and business-critical,
- dedicated maintainers and roadmap budget are allocated for 12+ months.

## Open questions
- Which exact object types must render in-chat in first release (charts/tables/maps/custom cards)?
- Is built-in ChatKit `Chart` acceptable for the first 1-2 milestones?
- Required STT UX: press-to-talk only or continuous dictation; per-message or streaming draft?
- Is data export/import from chart widgets needed in v1?
- What is the acceptable latency budget for STT round-trip?
