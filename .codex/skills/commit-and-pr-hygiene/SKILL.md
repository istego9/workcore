---
name: commit-and-pr-hygiene
description: >
  Keep AI-assisted changes reviewable with atomic commits, coherent PR structure,
  and explicit verification notes.
---

# Commit and PR Hygiene

## Goal
Make diffs reversible and easy to review.

## Recommended commit order
1) Specs/docs contracts
2) Implementation
3) Tests
4) Follow-up docs/runbooks

## PR checklist
- What changed and why
- Contract/schema impact
- Risk and rollback
- Commands run for verification
- Remaining TODOs/assumptions

## Guardrails
- Avoid "one giant commit".
- Avoid generic commit messages (`fix`, `update`).
- Keep unrelated refactors out of feature PRs.
