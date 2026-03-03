# Workflow Run Failures RCA (2026-03-04)

Status: Completed  
Type: Analysis-only (no runtime/API/schema changes)

## Scope
- Objective: identify main causes of run failures and isolate workflow design defects.
- Data source: local runtime Postgres (`workcore-local-postgres-1`, DB `workflow`).
- Time window in dataset: 2026-02-07 to 2026-03-03 (UTC).

## Executive summary
- Total runs: 1007
- Failed runs: 64 (6.4%)
- Root-cause class split:
  - Workflow design: 63/64 (98.4%)
  - External dependency (LLM rate limit): 1/64 (1.6%)

The dominant risk is workflow authoring quality (schema contracts and CEL expressions), not infrastructure instability.

## Evidence snapshot
- `runs` status counts: COMPLETED 935, FAILED 64, RUNNING 7, WAITING_FOR_INPUT 1.
- Failure categories by normalized error:
  - Schema empty `document_classification[]`: 24 (37.5%)
  - Schema missing `extracted_fields`: 10 (15.6%)
  - CEL ternary type mismatch: 9 (14.1%)
  - CEL comparison overload mismatch: 5 (7.8%)
  - CEL syntax / logical / missing state key: 9 (14.1%)
  - LLM TPM rate limit: 1 (1.6%)

## Top failing workflows/versions
- `uw_doc_classification_v1` / `wfv_3e9a122e`: 21 failed runs
- `uw_extraction_with_citations_v1` / `wfv_8713cca9`: 6 failed runs
- `PFM fm_trip_budget_plan` / `wfv_9cf325a2`: 4 failed runs
- `PFM fm_budget_builder` / `wfv_533ca92d`: 3 failed runs
- `PFM fm_budget_builder` / `wfv_308a07c5`: 3 failed runs

## Top failing nodes
- `classify_docs`: 25
- `extract_fields`: 10
- `route_missing`: 5
- `set_input_destination`: 4
- `set_budget_inputs`: 3
- `out_budget`: 3

## Workflow design defects observed
1. Strict output schemas without missing-data fallback branch
- Example: `classify_docs` requires non-empty array (`minItems: 1`) and fails hard on empty extraction result.

2. Agent output contract mismatch
- Example: required key missing (`extracted_fields`) or wrong top-level type (string instead of object).

3. CEL type-safety defects in routing/assignment logic
- Ternary/comparison/logical overload mismatches (`_?_:_`, `relation_eq`, `_&&_`).

4. Unprotected state access in expressions
- Missing fields produce `no such member in mapping` failures.

5. Expression complexity too high in single nodes
- Large output expression bodies (for example `out_budget`) increase syntax error probability and maintenance risk.

6. Retry/timeout controls are largely not configured on failing version+node pairs
- Failing nodes are mostly one-shot with no resilience tuning.

## Reliability and observability notes
- Failure events are present in `run_ledger`, but older failed runs (22) do not have `run_failed` ledger entries.
- `node_runs.usage` exists and is useful for cost analytics, but full coverage is not universal.
- Failed agent traces are not consistently populated (`trace_id` gaps).

## Practical conclusion
Primary remediation vector is workflow authoring discipline and publish-time quality gates:
- schema robustness,
- CEL safety,
- fallback branches for missing inputs,
- controlled retries/timeouts,
- smaller composable expressions.

Infrastructure hardening alone will not materially reduce failure rate in this dataset.
