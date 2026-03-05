---
name: integration-cutover-commander
description: Plan and run external integration cutovers with clear pre/post communication, execution checkpoints, incident triage inputs, and verification checklists. Use for endpoint/auth/domain migrations that affect partner teams.
---

# Integration Cutover Commander

## Goal
Reduce cutover risk and recovery time by enforcing a communication-first, evidence-based rollout process for external integrations.

## Use when
- Public endpoint path/host/auth changes.
- Migration windows with partner-facing impact.
- Multiple external teams need synchronized instructions.
- You need a structured pre-cutover and post-cutover communication pack.

## Inputs
- Exact change delta (old vs new path/auth/host).
- Cutover date/time window (UTC + local timezone).
- In-scope environments and domains.
- Validation commands and expected outcomes.
- Escalation channel and on-call owner.

If date/time is unclear, use absolute dates and add a blocking `TODO`.

## Workflow
1. Define migration matrix.
- Build explicit table:
  - old behavior
  - new behavior
  - compatibility period
  - final deprecated behavior (for example expected `404`)

2. Prepare pre-cutover notice.
- Include:
  - what changes
  - what does not change
  - exact action required by integrators
  - runnable curl checks
  - mandatory debug fields for escalation

3. Prepare execution checklist.
- Include step-by-step deployment checks:
  - contract checks
  - runtime checks
  - edge routing checks
  - auth profile checks
  - smoke tests on all in-scope hosts

4. Execute and capture evidence.
- Record absolute timestamp for key milestones.
- Capture pass/fail matrix for each host/path/auth profile.
- If failures occur, open incident mode and switch to fix-forward guidance.

5. Run incident response protocol when needed.
- Request:
  - UTC timestamp
  - host/method/path
  - correlation id
  - status and response body
- Classify:
  - platform defect
  - integration misuse
  - config mismatch
  - unknown (needs more data)

6. Prepare post-cutover message.
- Confirm completion timestamp.
- Re-state canonical endpoint/auth.
- Re-state deprecated behavior and required migration action.

## Communication templates
Use this concise structure for both pre and post messages:

```md
Subject: <service> cutover: <summary>

Hello team,

Date/time (UTC): <...>
Status: <planned/completed/in-progress>

Changes:
- ...

Required action:
1. ...
2. ...

Validation:
- command:
- expected result:

If issues remain, send:
- UTC timestamp
- host + method + path
- correlation id
- status + body
```

## Output template
```md
# Cutover Command Log

## Scope and date
- ...

## Pre-cutover package
- notice:
- checklist:

## Execution evidence
- host matrix:
- auth matrix:
- timestamps:

## Incidents
- none | list with classification

## Post-cutover package
- completion notice:
- remaining actions:
```

## Guardrails
- Never use relative time words without absolute date/time.
- Never publish secret values in examples.
- Do not claim rollback support when the plan is fix-forward only.
- Keep partner instructions executable and contract-accurate.

## Done criteria
- Pre/post communications are prepared and versioned.
- Execution checklist includes all affected hosts and auth profiles.
- Escalation data requirements are explicit.
- Final status is recorded with timestamp and evidence.
