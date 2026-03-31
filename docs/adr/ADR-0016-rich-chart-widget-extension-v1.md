# ADR-0016: RichChart Widget Extension v1

Date: 2026-03-31  
Status: Proposed

## Context
Current chat widget evolution mixes two different semantics under the same component name:

- stock ChatKit already defines a native `Chart` widget intended for simple chart rendering;
- WorkCore fork frontend currently uses `Chart` as a custom Nivo-based renderer contract with a much broader `chart_type` registry and pass-through `nivo_props`.

This creates three problems:

1. The public contract is ambiguous because the same component name implies different payload semantics.
2. External integrators cannot tell whether a payload is stock ChatKit-compatible or WorkCore-specific.
3. Rich chart rendering depends on a custom renderer surface, but the current public wording makes it look like a generic ChatKit capability.

Product direction requires expanded charting and client-side interactivity, while preserving a single `/chat` transport contract and avoiding a full chat protocol fork.

This decision is platform-wide and not partner-specific:
- `RichChart` must be part of the general public compatibility model for WorkCore chat integrations;
- all public API hosts that expose the same public chat surface must expose the same compatibility semantics;
- no partner should require a custom contract fork just to use rich chart rendering.

## Decision
Adopt a custom rich widget extension named `RichChart` for WorkCore-specific chart rendering.

1. Keep a single canonical chat transport contract.
- `POST /chat` remains the only canonical public chat endpoint.
- `thread.item.done` / `item.type = "widget"` remains the widget delivery mechanism.
- No second top-level chat protocol or parallel transport contract is introduced.

2. Introduce `RichChart` as a custom widget extension component.
- `RichChart` is not a synonym for stock ChatKit `Chart`.
- `RichChart` is the only public name for the WorkCore rich chart contract.
- Existing internal/fork support for legacy custom `Chart` may remain temporarily as a migration alias, but public GA payloads must emit `RichChart`.

3. Scope `RichChart v1` to client-only interactivity.
- Supported interactions are renderer-local only: hover, tooltip, responsive resize, legend visibility, local theme/layout adaptation, and other interactions that do not require server round-trips.
- `RichChart v1` does not support server callbacks, click-to-fetch, drilldown requests, widget actions, or cross-widget orchestration.

4. Keep schema and capability roles separate.
- Schema remains the source of truth for payload shape.
- `GET /integration-capabilities` advertises whether `RichChart` is supported on the current public host / client surface.
- This compatibility signal is part of the platform-wide public integration contract, not a partner-specific override.
- Capability negotiation must not redefine the widget payload itself.

5. Require explicit fallback behavior.
- Server must emit `RichChart` only when the client surface is known to support it.
- When support is absent or unknown, server must emit a native fallback widget instead of a `RichChart` payload.

## Consequences
### Positive
- Removes semantic collision with stock ChatKit `Chart`.
- Preserves freedom to support rich Nivo-based charts and broader chart registries.
- Keeps the `/chat` transport stable while allowing richer widget contracts on top.
- Makes client-only interactivity explicit and testable.

### Neutral/Tradeoff
- External clients now need either:
  - WorkCore `chat-fork`, or
  - their own renderer for `RichChart`, or
  - fallback-only behavior.
- Rich chart support is no longer implied for all generic ChatKit consumers.
- Public host drift becomes more visible because all public hosts are expected to advertise the same compatibility system.

### Compatibility
- Additive at the transport level: `/chat` and widget item delivery remain unchanged.
- Breaking only at the extension naming layer if handled without migration; therefore migration support is required:
  - reference renderer should accept both legacy `Chart` and new `RichChart` during transition;
  - server-generated payloads must migrate to `RichChart`;
  - public docs and examples must stop presenting the WorkCore custom contract as `Chart`.

## Follow-up
- Define the exact `RichChart v1` payload schema and examples.
- Extend `GET /integration-capabilities` with `widget_extensions.RichChart`.
- Add public-host consistency checks so all public API hosts expose the same capability surface.
- Add explicit fallback selection rules and deployment smoke checks for public hosts.
- Revisit `RichChart v2` only when server-backed interactivity becomes a real requirement.
