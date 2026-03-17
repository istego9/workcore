---
name: cross-team-incident-response
description: >
  Handle incoming issue reports from other teams quickly: triage, reproduce, fix when possible,
  and prepare a clear response letter with correct integration instructions. Use when a
  "письмо от другой команды" describes an incident, integration failure, wrong request format,
  or unclear API contract usage.
---

# Cross-Team Incident Response

## Goal
Minimize time-to-clarity and time-to-recovery for inter-team incidents.

## Workflow
1) Parse the incoming message and extract:
- reported symptom and impact
- environment and time window
- expected vs actual behavior
- request/response samples
- correlation ID or trace IDs

2) If data is missing, send a short unblock request immediately:
- exact timestamp (with timezone)
- failing endpoint/method
- sample payload (without secrets)
- response code/body

3) Run fast triage:
- check logs/traces by correlation ID + timestamp
- reproduce with the same payload/version
- classify the issue:
  - platform defect
  - integration misuse / contract mismatch
  - configuration mismatch
  - unknown (needs more data)

4) Resolve or mitigate:
- for platform defect: implement the smallest safe fix and verify
- for config mismatch: apply safe correction and verify
- for unknown: provide exact missing inputs and next ETA

5) Prepare response letter:
- status (`resolved`, `in progress`, `blocked`)
- root cause (confirmed or hypothesis)
- what was changed on our side
- what their team must change (if integration misuse)
- correct integration steps with exact contract fields
- clear verification checklist

## Integration Instruction Rules
- Use only documented contracts and existing fields/endpoints.
- If another team sends incorrect payload/flow, include:
  - `Incorrect:` short invalid pattern
  - `Correct:` short valid pattern
- Provide executable validation steps, not abstract advice.
- Never include secrets/tokens in examples.

## Response Template
```md
Subject: <Service> integration issue: <short summary>

Hi <Team>,

We reviewed your report from <date/time with timezone>.
Status: <resolved/in progress/blocked>

What happened:
- <symptom + impact>

Root cause:
- <confirmed cause or hypothesis>

What we changed on our side:
- <fix/mitigation + rollout state>

What your team should change:
1. <action 1>
2. <action 2>

Correct integration example:
- Endpoint: <...>
- Method: <...>
- Required headers: <...>
- Payload shape: <...>

How to verify:
1. <check 1>
2. <check 2>

If it still fails, please send:
- <correlation ID>
- <timestamp + timezone>
- <response code/body>

Regards,
<Your team>
```

## Guardrails
- Do not invent fields, APIs, or behaviors.
- Keep communication factual and actionable.
- Prioritize restore-first; then follow up with deeper cleanup.
