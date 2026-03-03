# Weekly Workflow Recommendation Framework (2026-03-04)

Status: Completed  
Type: Analysis-only (no runtime/API/schema changes)

## Goal
Define a repeatable weekly process to improve workflow outcomes across four targets:
- lower token cost,
- higher answer quality,
- higher stability,
- higher operational reliability.

## Inputs (current platform)
Use existing persisted signals first:
- `runs` (status, timing, workflow/version dimensions)
- `node_runs` (status, attempts, errors, usage, trace)
- `run_ledger` (event timeline, node_failed/run_failed payloads)
- `workflow_versions` + `workflows` (design dimensions and version drift)

## Weekly KPI set

### 1) Cost KPIs
- `tokens_per_success_run` by `workflow_id + version_id`
- `token_waste_rate = tokens_failed_runs / tokens_all_runs`
- `top_token_nodes` (Pareto by total token share)
- WoW token regression per workflow version

### 2) Quality KPIs
- `first_pass_success_rate` (completed without failure)
- `schema_first_pass_rate` (agent/schema nodes passing without validation errors)
- `missing-data-fallback_rate` (share of runs routed to collect/clarify path)
- `post-response-rework_proxy` (runs that fail then rerun the same node or require extra interaction)

### 3) Stability KPIs
- run fail rate by workflow/version
- node fail rate by workflow/version/node
- normalized error taxonomy distribution (schema vs CEL vs external)
- p50/p95 run duration and tail outliers

### 4) Reliability KPIs
- stuck run backlog (`RUNNING` or `WAITING_FOR_INPUT` older than SLA)
- `usage_coverage` for agent nodes
- `trace_coverage` for failed nodes
- `ledger_completeness` (expected terminal events present)

## Decision engine (metric -> recommendation)

### Rule family A: Schema/contract failures
Trigger:
- schema-related failures above threshold (for example > 3% per version or > 3 events/week)
Action:
- relax strictness where business-safe (`minItems`, nullable fields),
- add explicit missing-data branch before hard fail,
- enforce post-agent mapping node (`set_state`) with explicit typing.

### Rule family B: CEL failures
Trigger:
- CEL type/syntax/missing-state errors above threshold
Action:
- replace inline branch math with staged `set_state` boolean flags,
- add state existence guards before dereference,
- split large expressions into smaller composable nodes.

### Rule family C: Cost regressions
Trigger:
- WoW token growth > threshold (for example +20%) without quality gain
Action:
- trim prompt context,
- cap extraction scope,
- use metadata-first document strategy and fetch full content only on demand,
- reduce over-detailed schema when not required by downstream logic.

### Rule family D: Reliability gaps
Trigger:
- low observability coverage (usage/trace/ledger) or stuck backlog increase
Action:
- prioritize instrumentation fixes,
- set per-node timeout and retry defaults for volatile nodes,
- add operator-facing alerting for stale non-terminal runs.

## Weekly operating cadence
1. Extract last 7 days and previous 28 days baseline.
2. Compute KPI deltas by workflow/version and by node.
3. Rank remediation candidates by impact score:
   - `impact = failure_frequency * token_cost * business_criticality`.
4. Select top 3 candidates for next iteration.
5. For each selected workflow, publish explicit recommendations:
   - what to change,
   - expected KPI effect,
   - rollback condition.
6. Next week, compare actual deltas against expected effect.

## Minimal weekly deliverable format
For each impacted workflow/version include:
- KPI snapshot (cost/quality/stability/reliability)
- top failure categories with counts
- top expensive nodes by token share
- recommendation list (ordered by impact)
- rollout risk and rollback trigger

## Suggested thresholds (initial defaults)
- Fail-rate warning: > 5% per workflow version
- Fail-rate critical: > 10%
- WoW token regression warning: > 20%
- Usage coverage warning: < 90% of agent node runs
- Trace coverage warning on failed nodes: < 95%
- Stuck run SLA breach: non-terminal older than 30 minutes (environment-specific)

These thresholds should be tuned after 2-4 weekly cycles.

## Next instrumentation increments (small, high ROI)
1. Normalize runtime errors into stable `error_code/error_class` taxonomy.
2. Ensure failed agent executions always persist `trace_id`.
3. Persist token/latency fields for all live agent calls in a uniform shape.
4. Add automated weekly report job that emits recommendation-ready artifacts.

## Success criteria
Framework is considered effective when, over consecutive weeks:
- workflow-design failure share decreases,
- token waste rate decreases,
- no regression in completion quality,
- observability coverage rises to target thresholds.
