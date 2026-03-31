# ChatKit RichChart v1 Specification

Status: Proposed  
Date: 2026-03-31  
Related ADR: `docs/adr/ADR-0016-rich-chart-widget-extension-v1.md`

## Purpose
Define the WorkCore `RichChart` widget extension as a custom chart-rendering contract for chat surfaces that support the WorkCore rich widget renderer.

`RichChart v1` is intended for:
- expanded chart type coverage,
- richer local rendering controls,
- client-only interactivity,
- transport compatibility with the existing `/chat` widget item model.

`RichChart v1` is not intended to be a stock ChatKit-native component.

`RichChart v1` is a platform-wide public compatibility feature:
- it applies to the shared WorkCore public chat contract, not to a single partner;
- all public API hosts that expose the same `/chat` contract must expose the same `RichChart` compatibility semantics;
- client capability negotiation must be generic and reusable across external integrators.

## Goals
- Keep a single canonical `/chat` transport contract.
- Make the rich chart contract explicit and unambiguous.
- Preserve compatibility with native widget fallback for clients that do not support rich chart rendering.
- Support client-only interactivity without introducing widget action callbacks.

## Non-goals
- No new top-level chat endpoint.
- No server-driven chart interactions in v1.
- No click actions, drilldown requests, data refresh callbacks, or cross-widget synchronization.
- No redefinition of stock ChatKit `Chart`.

## Single-contract boundary
`RichChart` is an extension component inside the existing widget transport.

The following remain unchanged:
- `POST /chat`
- SSE stream event framing
- `thread.item.done`
- `item.type = "widget"`

The only new payload surface is the widget component type inside `item.widget`.

## Component contract
Canonical component type:

```json
{
  "type": "RichChart",
  "spec_version": "1",
  "chart_type": "line",
  "data": [],
  "series": [],
  "nivo_props": {}
}
```

### Field definitions
- `type`: required, must equal `RichChart`
- `spec_version`: required, must equal `"1"`
- `chart_type`: required string; chooses renderer adapter
- `data`: required; chart data payload
- `series`: optional; series definitions used by cartesian/multi-series charts
- `nivo_props`: optional object; pass-through renderer configuration
- `xAxis`: optional string or object; x-axis key/config used by tabular cartesian payloads
- `title`: optional string
- `subtitle`: optional string
- `description`: optional string

### Data shape
`data` may be:
- array of objects for tabular/cartesian charts
- object for hierarchy/network-style charts

The exact required structure depends on `chart_type`.

### Unsupported fields in v1
The following concepts are explicitly out of scope for `RichChart v1` and must not appear in the public contract:
- `onClickAction`
- `onSelectAction`
- `drilldown`
- `load_more`
- `refresh_action`
- any other server callback or chat action binding

## Supported chart types
`RichChart v1` uses the current WorkCore rich renderer registry:

- `bar`
- `line`
- `pie`
- `area-bump`
- `bump`
- `boxplot`
- `bullet`
- `calendar`
- `chord`
- `circle-packing`
- `funnel`
- `geo`
- `heatmap`
- `icicle`
- `marimekko`
- `network`
- `parallel-coordinates`
- `polar-bar`
- `radar`
- `radial-bar`
- `sankey`
- `scatterplot`
- `stream`
- `sunburst`
- `swarmplot`
- `tree`
- `treemap`
- `waffle`

## Interactivity model
`RichChart v1` supports client-only interactivity.

Allowed:
- hover state
- tooltip display
- legend show/hide when supported by the renderer
- responsive resize / layout recomputation
- local theme adaptation
- local visual highlighting that does not trigger network requests

Not allowed:
- server round-trips on chart interaction
- widget action dispatch from the chart
- lazy data loading
- drilldown requests
- chat-thread side effects triggered by chart events

## Fallback model
`RichChart` is emitted only when the target client surface is known to support it.

If support is absent or unknown:
- server must not emit `RichChart`
- server must emit a native fallback widget instead

Minimum fallback requirement:
- a native `Card` containing a textual summary of the chart data

Optional richer fallback:
- `DataTable`
- image-based chart preview
- both

Fallback selection is server-owned and is not part of the `RichChart` payload itself.

## Capability negotiation
Schema is the source of truth for payload shape. Capability negotiation is discovery-only.

Compatibility negotiation is general-purpose:
- not EPAM-specific;
- not tied to `api.runwcr.com` only;
- reusable by any external client integrating against the public WorkCore chat surface.

### Server discovery payload
`GET /integration-capabilities` should advertise `RichChart` support under a widget extension section similar to:

```json
{
  "widget_extensions": {
    "RichChart": {
      "component_type": "RichChart",
      "schema_url": "https://<host>/schemas/chatkit-widget-extension.schema.json",
      "spec_versions": ["1"],
      "interactive_mode": "client_only",
      "supported_chart_types": ["bar", "line", "pie"]
    }
  }
}
```

### Client support hint
Client requests should be able to advertise rich widget support additively via request metadata, using a shape similar to:

```json
{
  "metadata": {
    "client_capabilities": {
      "widget_extensions": {
        "RichChart": {
          "spec_versions": ["1"]
        }
      }
    }
  }
}
```

The exact field must remain additive within request metadata, not a new top-level chat transport.

### Public host consistency
The following rule applies to every public API host that exposes the same public chat surface:
- if `/chat`, `/agent-integration-kit*`, and `/openapi.yaml` are exposed, `GET /integration-capabilities` must also be exposed;
- `RichChart` capability semantics must be consistent across those hosts;
- host-specific rollout lag is a deployment defect, not a supported compatibility mode.

## Migration from legacy custom `Chart`
Current WorkCore rich chart payloads use `Chart` as a custom extension name. That naming is transitional only.

Migration rules:
- public GA contract emits `RichChart`
- reference renderer accepts `RichChart` and only those legacy custom `Chart` payloads that include explicit RichChart-only markers
- public docs, examples, and negotiation output must use `RichChart` only
- the stock ChatKit meaning of `Chart` must remain untouched

## Canonical examples
### Budget donut
```json
{
  "type": "RichChart",
  "spec_version": "1",
  "title": "Budget allocation",
  "chart_type": "pie",
  "data": [
    { "id": "Needs", "value": 55 },
    { "id": "Savings", "value": 25 },
    { "id": "Wants", "value": 20 }
  ],
  "nivo_props": {
    "height": 280,
    "innerRadius": 0.6,
    "padAngle": 1,
    "cornerRadius": 3
  }
}
```

### Timeline line chart
```json
{
  "type": "RichChart",
  "spec_version": "1",
  "title": "Cashflow trend",
  "chart_type": "line",
  "xAxis": "month",
  "data": [
    { "month": "Jan", "actual": 1200, "target": 1100 },
    { "month": "Feb", "actual": 1350, "target": 1200 },
    { "month": "Mar", "actual": 1280, "target": 1250 }
  ],
  "series": [
    { "type": "line", "dataKey": "actual", "label": "Actual" },
    { "type": "line", "dataKey": "target", "label": "Target" }
  ],
  "nivo_props": {
    "height": 280,
    "curve": "monotoneX"
  }
}
```

## Validation rules
- `type` must equal `RichChart`
- `spec_version` must equal `"1"`
- `chart_type` must be present
- `data` must be present
- `nivo_props` must be an object when provided
- `series` is optional globally, but required by chart types that need series definitions
- unknown chart types must fail safely on the client
- unsupported payloads must render a non-fatal fallback component, not break the thread UI

## Security and observability
- Do not log full chart payloads by default.
- Logs may capture:
  - component type
  - spec version
  - chart type
  - fallback vs native path
  - correlation id / trace id
- Rich chart rendering errors must be observable without exposing business payload contents.

## Rollout semantics
Phase 1:
- publish spec and capability fields
- keep server fallback default
- keep `RichChart` emission behind a runtime feature flag that defaults to off

Phase 2:
- validate public host matrix on every public API host
- enable `RichChart` emission only for known-capable clients after matrix validation passes

Phase 3:
- deprecate legacy custom `Chart` alias in the reference renderer

Public rollout requirement:
- validate the same behavior on every public host, including `api.hq21.tech` and `api.runwcr.com`
- future public domains must be added to the same smoke matrix before release sign-off

## Open questions
- Whether `DataTable` remains under the same extension schema file or gets its own versioning track.
- Whether fallback should prefer `DataTable`, image, or `Card` summary per workflow family.
- Whether `supported_chart_types` in negotiation should advertise the full registry or a narrower production-ready subset on each host.
