---
name: docs-adr
description: Write developer documentation and ADRs: architecture overview, API docs, runbooks, and operational troubleshooting guides. Use when shipping features, adding endpoints, or changing runtime behavior.
---

# Docs and ADRs

## Outputs
- `docs/architecture/*` (overview + diagrams if used)
- `docs/api/*` (how to call endpoints, auth, examples)
- `docs/runbooks/*` (ops procedures: replay, DLQ, webhook debugging)
- `docs/adr/*` (decisions with context and trade-offs)

## Steps
1) Document "how it works" and "how to use it".
2) Include copy-paste examples for APIs and webhooks.
3) Include troubleshooting steps tied to observability signals.

## Definition of done
- A new engineer can start a run and debug a failure using docs alone.
- All public endpoints have documentation and examples.
