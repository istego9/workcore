---
name: incident-runbook
description: >
  Create practical runbooks and postmortem templates for on-call debugging.
  Use when adding critical flows, alerts, or integration dependencies.
---

# Incident Runbook

## Goal
Reduce MTTR with concrete troubleshooting steps.

## Deliverables
- `docs/runbooks/<system>.md` for critical systems
- `docs/postmortems/template.md` for structured incident analysis

## Must include
1) Symptoms and blast radius
2) Health checks and exact commands
3) Key logs/metrics/traces to inspect
4) Top likely root causes
5) Remediation and rollback steps
6) Escalation criteria

## Guardrails
- Avoid vague instructions like "check logs".
- Use exact paths, endpoints, and commands.
