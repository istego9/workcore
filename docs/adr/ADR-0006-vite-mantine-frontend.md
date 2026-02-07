# ADR-0006: Vite + Mantine for Builder UI

Date: 2026-01-29
Status: Accepted

## Context
We need a fast developer workflow and a component library to build the workflow builder UI.

## Decision
Use Vite for the frontend build tool and Mantine as the React UI component library.

## Consequences
- Fast local development via Vite HMR.
- Consistent component primitives and theming with Mantine.
- UI tests will run headless by default in CI.

## Alternatives Considered
- CRA: slower dev cycle and deprecated.
- Next.js + SSR: unnecessary complexity for MVP SPA.
- Custom UI from scratch: higher time-to-delivery.
