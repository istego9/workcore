# Agent Autonomy Harness

Date: 2026-02-20
Status: Draft

## Purpose
Provide one operational contract so AI agents can execute WorkCore tasks autonomously with predictable quality.

## Source principles
Based on Harness Engineering guidance:
- reduce conversion entropy between request and implementation
- make outputs machine-checkable
- optimize using repeatable harness loops

Reference: https://openai.com/index/harness-engineering/

## 1) Task intake contract (mandatory)
Every agent task must start with this normalized input:

```yaml
task_id: <string>
objective: <single measurable outcome>
scope_in:
  - <allowed modules/files>
scope_out:
  - <explicit exclusions>
constraints:
  - no new deps
  - preserve backward compatibility unless approved
acceptance:
  - <machine-checkable checks>
artifacts:
  - <required outputs: docs/tests/screenshots/links>
```

If any field is missing:
- add explicit TODO
- stop before contract-changing implementation

## 2) Work modes

### Mode A: Contract-changing work (A-E in AGENTS.md)
1. Update spec artifacts first (`docs/api`, `docs/architecture`, `db/migrations`, ADR when needed).
2. Create action-item checklist (8 mandatory items from AGENTS.md).
3. Implement code.
4. Add/adjust tests.
5. Update changelog and rollout notes.

### Mode B: Non-contract work (F-G)
1. Implement smallest safe change.
2. Add/adjust tests when behavior changes.
3. Record residual risks and validation executed.

## 3) Harness loop (mandatory)
For each meaningful change, run this loop:
1. `Define`: formal expected behavior (inputs/outputs/errors).
2. `Implement`: minimal diff to satisfy behavior.
3. `Evaluate`: run deterministic checks.
4. `Score`: compare against explicit thresholds.
5. `Tighten`: fix regressions and repeat.

## 4) Required quality gates
Use relevant commands from `AGENTS.md` and `docs/DEV_WORKFLOW.md`:
- `./scripts/archctl_validate.sh`
- `./.venv/bin/python -m pytest apps/orchestrator/tests`
- `cd apps/builder && npm run test:unit`
- `cd apps/builder && npm run test:e2e` (when UI/runtime paths touched)
- `./scripts/dev_check.sh`

Never claim a gate was run if it was not executed.

## 5) Routing quality harness (orchestrator)
When routing logic or policies change:
- Evaluate `POST /orchestrator/eval/replay` with labeled cases.
- Track these metrics per change:
  - `action_accuracy`
  - `workflow_accuracy`
  - `exact_match_rate`
- Enforce non-regression threshold in CI before merge.

## 6) Agent output contract
Agent must return:
1. classification (A-G)
2. action items (for A-E)
3. files changed
4. tests run + outcomes
5. unresolved TODOs/questions
6. rollback notes (for risky changes)

## 7) Stop conditions and escalation
Stop and escalate when:
- required contract data is missing
- requested behavior conflicts with existing API/schema guarantees
- security policy (secrets, PII, outbound access) is ambiguous
- observed workspace changes are unexpected and not attributable

## 8) Repo entrypoints for agents
- Architecture overview: `docs/architecture/overview.md`
- Runtime semantics: `docs/architecture/runtime.md`
- Data model: `docs/architecture/data-model.md`
- API contract: `docs/api/openapi.yaml`
- Process gates: `docs/DEV_WORKFLOW.md`
- Root policy: `AGENTS.md`
