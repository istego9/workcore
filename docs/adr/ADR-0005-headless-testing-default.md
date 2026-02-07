# ADR-0005: Headless Testing by Default

Date: 2026-01-29
Status: Accepted

## Context
We need reliable, repeatable automated tests for UI and E2E flows in CI.

## Decision
All automated browser/UI/E2E tests run headless by default. Headed mode is allowed only for local debugging.

## Consequences
- CI does not require a graphical environment.
- Tests must avoid dependencies on OS-level UI prompts.
- Local developers can still use headed mode to debug failures.

## Alternatives Considered
- Headed-only tests: higher flake rate and CI complexity.
- Mixed defaults: inconsistent execution environments.
