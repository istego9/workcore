# ADR-0008: Batch Assignments for Set State Nodes

Date: 2026-02-18
Status: Accepted

## Context
Large workflows often contain many consecutive `set_state` nodes that only map values into runtime state. This makes graphs noisy, harder to review, and slower to maintain for agents and human operators.

The existing `set_state` contract supports only one assignment per node (`target` + `expression`).

## Decision
Extend `set_state` with additive batch assignment support:
- Keep legacy config: `target` + `expression`.
- Add `assignments[]` config with items `{ target, expression }`.
- Runtime executes `assignments[]` in order when present; legacy fields are fallback.
- Builder supports editing multiple assignments in a single `set_state` node.

Backward compatibility policy:
- Existing workflows using legacy config remain valid and execute unchanged.
- No endpoint removals, no DB migrations, no event schema changes.

## Consequences
- Workflows can collapse many technical mapping nodes into fewer nodes.
- Authoring and review focus moves from mechanical state wiring to business logic.
- Runtime behavior remains deterministic because assignment order is explicit.

## Alternatives Considered
- Introduce a new node type (`state_patch`): rejected for now to avoid expanding node taxonomy and migration complexity.
- Auto-merge all agent outputs without explicit mappings: rejected due to reduced control/auditability.
