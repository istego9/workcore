---
name: workflow-builder-ui
description: Implement the workflow builder UI: graph canvas, node palette, edge connections, config panels, validation, and persistence. Use when building or extending the visual graph editor or adding node types/config forms.
---

# Workflow Builder UI

## Core requirements
- Allow users to add nodes, connect edges, and configure nodes via a side panel.
- Validate graph sanity (no orphan nodes, has Start -> End path).
- Auto-save drafts and support publish/rollback.

## Steps
1) Implement canvas basics:
   - Add/move nodes, connect edges, zoom/pan
2) Implement palette:
   - Start is always present (or enforced by validation)
   - Provide MVP node types
3) Implement node config panels:
   - Typed forms
   - JSON schema editor/viewer for object variables and structured outputs
4) Implement validations:
   - Graph connectivity
   - Required config fields
   - While requires max_iterations
5) Integrate with backend:
   - Load draft
   - Save draft (nodes/edges/config)
   - Publish/rollback actions

## Definition of done
- A user can build a minimal workflow and publish it.
- Invalid graphs are blocked with clear messages.
- Draft changes persist reliably.
