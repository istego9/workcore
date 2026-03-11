# Run Debug Inspector

## Purpose
Provide a deterministic operator workflow for run-level RCA and support escalation from Builder Execution history.

## Entry point
1. Open Builder and click `History`.
2. Select a run card and click `Open Run Debug`.

## What to inspect
1. `Run summary`: run/workflow/version/project IDs, status/mode, timestamps, correlation/trace identifiers.
2. `Timeline`: normalized ledger events grouped by run -> node -> attempt.
3. `Node attempts`: per-node attempt chronology with status, errors, trace id, output/usage preview.
4. `Retry / rerun history`: inferred automatic retry versus manual rerun transitions.
5. `Last good output`: deterministic rule:
   - If run is `COMPLETED` and `run.outputs` exists, use `run.outputs`.
   - Otherwise use the latest `RESOLVED` node attempt output in execution order.

## Debug actions
1. `Refresh inspector` reloads `GET /runs/{run_id}` and `GET /runs/{run_id}/ledger`.
2. `Rerun node` uses `POST /runs/{run_id}/rerun-node` with `scope=node_only|downstream`.
3. `Cancel run` uses `POST /runs/{run_id}/cancel` when cancellable.

## Support bundle export
`Export support bundle` downloads a JSON bundle containing:
- run summary + selected metadata
- typed error info
- normalized timeline
- node attempts
- retry/rerun history
- last good output
- bounded ledger excerpt

### Redaction guardrails
- Secrets and auth material are redacted (`token`, `secret`, `password`, signatures, credentials).
- Inline artifact body fields are redacted when `artifact_ref` is present.
- Heavy binary fields (for example `image_base64`) are redacted.
- Artifact references are preserved.

## Escalation package checklist
1. Attach exported support bundle.
2. Include run id, workflow id, version id, project id.
3. Include correlation id and relevant trace ids.
4. State whether rerun was attempted (`node_only` or `downstream`) and outcome.
