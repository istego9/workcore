---
name: ai-change-explainer
description: >
  Produce a concise, auditable explanation of AI-assisted diffs for reviewers.
  Use before PR submission or when asked to summarize impact.
---

# AI Change Explainer

## Goal
Convert implementation diff into a reviewer-friendly impact report.

## Output sections
1) Intent
2) Spec/contract changes
3) Code changes by module
4) Data/schema impact
5) Risks and mitigations
6) Verification commands and results
7) Rollout/rollback notes

## Guardrails
- Never claim checks/tests were run if they were not.
- Call out assumptions and missing validations explicitly.
