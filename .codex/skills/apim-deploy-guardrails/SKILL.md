---
name: apim-deploy-guardrails
description: Harden APIM and edge deployment changes with deterministic preflight checks, policy sanity checks, contract alignment, and rollback notes. Use when changes touch APIM policies, Front Door routing, Entra OAuth gateway behavior, or partner mapping scripts.
---

# APIM Deploy Guardrails

## Goal
Prevent production regressions during APIM and edge routing changes by enforcing a repeatable guardrail workflow before rollout.

## Use when
- Deployments touch:
  - `deploy/azure/scripts/deploy_apim.sh`
  - `deploy/azure/scripts/deploy_frontdoor.sh`
  - `deploy/azure/scripts/apim_partner_onboard.sh`
  - `deploy/azure/scripts/apim_partner_rotate_secret.sh`
  - `deploy/azure/scripts/apim_partner_revoke.sh`
- Public auth model or path routing changes (for example `/chat`, OAuth, header injection).
- Incidents are linked to APIM policy parsing, CLI version drift, or partner map synchronization.

## Required inputs
- Target environment (`prod`/`staging`/`dev`).
- Affected hostnames and paths.
- Expected auth model (OAuth, public exceptions).
- Current rollout plan file under `docs/exec-plans/active/`.

If any input is missing, add `TODO` in the report and continue with safe assumptions.

## Workflow
1. Classify the task.
- Mark as A-E or F based on `AGENTS.md`.
- For A-E, verify spec-first artifacts are listed before implementation.

2. Run static script checks.
- Run:
  - `bash -n deploy/azure/scripts/deploy_apim.sh`
  - `bash -n deploy/azure/scripts/deploy_frontdoor.sh`
  - `bash -n deploy/azure/scripts/apim_partner_onboard.sh`
  - `bash -n deploy/azure/scripts/apim_partner_rotate_secret.sh`
  - `bash -n deploy/azure/scripts/apim_partner_revoke.sh`
- Fail fast on syntax errors.

3. Validate policy invariants.
- Confirm routing invariants in APIM policy:
  - Public endpoints remain explicitly allowed.
  - Protected endpoints enforce JWT validation.
  - Chat route handling remains intentional (`/chat` mapping and backend target).
  - Correlation headers are injected when absent.
- Confirm no accidental auth bypass in `choose/when` branches.

4. Validate partner map safety.
- Ensure partner map updates are additive unless explicit revoke is requested.
- Verify "empty config" does not silently wipe APIM partner map.
- Confirm unknown app behavior matches `APIM_ENFORCE_PARTNER_MAP`.

5. Validate contract alignment.
- Cross-check:
  - `docs/api/openapi.yaml`
  - `docs/api/reference.md`
  - `docs/integration/workcore-api-integration-guide.md`
- Confirm gateway behavior matches docs (`/chat` canonical path, auth requirements).

6. Validate rollout and rollback path.
- Ensure rollout sequence is explicit (infra -> runtime -> policy -> edge switch).
- Ensure rollback sequence is explicit and non-destructive.
- Confirm pre-prod dry-run evidence exists or add explicit `TODO`.

7. Run repository checks relevant to the touched area.
- Minimum:
  - `./scripts/archctl_validate.sh`
  - `./scripts/dev_check.sh`
- If runtime/API behavior changed, include:
  - `./.venv/bin/python -m pytest apps/orchestrator/tests`

## Output template
Use this exact structure in your report:

```md
# APIM Guardrail Report

## Scope
- Environment:
- Files:
- Change class:

## Checks
- Syntax:
- Policy invariants:
- Partner map invariants:
- Contract alignment:
- Rollout/rollback:

## Findings
- [P0/P1/P2] ...

## TODOs
- ...

## Go/No-Go
- Decision:
- Conditions:
```

## Guardrails
- Never print or commit secrets/tokens.
- Never use destructive git commands.
- Do not invent endpoints, headers, or policy fields.
- If a branch condition is ambiguous, mark as risk and block rollout recommendation.
- Never claim checks passed unless you ran them.

## Done criteria
- No unresolved P0 findings.
- Contract/docs/policy are aligned.
- Rollout and rollback notes are concrete and environment-specific.
- Residual risks are explicitly listed.
