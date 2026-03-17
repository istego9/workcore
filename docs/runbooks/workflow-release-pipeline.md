# Workflow Release Pipeline

## Purpose
Provide an operator runbook for Builder release promotion:
Validate -> Simulate -> Diff -> Publish -> Bind -> Smoke -> Observe.

## Symptoms and blast radius
1. Release drawer cannot confirm Bind status after routing update.
2. Smoke run fails, hangs, or does not produce a usable `run_id`.
3. Release report export succeeds locally but handoff evidence is incomplete.
4. Operators see conflicting states between Builder badges, project defaults, and runtime behavior.

Blast radius:
- project-scoped chat routing
- direct orchestrator routing for workflows registered in project routing index
- operator handoff evidence during publish/cutover

## Health checks and exact commands
1. Confirm API/docs surface:
```bash
curl -fsS http://127.0.0.1:8000/openapi.yaml | rg '^  /projects/.*/workflow-definitions'
```
2. Confirm project workflow definition readback:
```bash
curl -fsS "http://127.0.0.1:8000/projects/$PROJECT_ID/workflow-definitions/$WORKFLOW_ID" \
  -H "Authorization: Bearer $WORKCORE_API_AUTH_TOKEN" \
  -H "X-Tenant-Id: $TENANT_ID" | jq
```
3. Confirm default chat workflow on project:
```bash
curl -fsS "http://127.0.0.1:8000/projects?limit=200" \
  -H "Authorization: Bearer $WORKCORE_API_AUTH_TOKEN" \
  -H "X-Tenant-Id: $TENANT_ID" | jq '.items[] | select(.project_id == env.PROJECT_ID)'
```
4. Re-run live operator acceptance locally:
```bash
cd apps/builder && playwright test e2e/release-pipeline.live.spec.ts e2e/run-debug.live.spec.ts
```

## Key logs and evidence to inspect
1. Builder release pipeline logs for `bind_updated`, `smoke_started`, `smoke_completed`, and `release_report_exported`.
2. API integration logs for workflow-definition `upsert/read/list` with matching `correlation_id`.
3. Run Debug support bundle for:
   - `ledger_truncated`
   - `ledger_entries_included`
   - `ledger_entries_available`
   - `ledger_entries_available_exact`
4. Release report JSON for:
   - `validation_result`
   - `simulation_result`
   - `bind_targets`
   - `smoke_result`
   - `run_ids`
   - `correlation_ids`

## Common root causes
1. Workflow was published but routing definition was not confirmed by server readback.
2. Project default chat workflow and routing definition point to different workflows.
3. Smoke run started against an old version because publish/bind ordering was skipped.
4. Export JSON was downloaded but not validated for required fields or redaction.

## Remediation and rollback
1. If Bind readback fails, do not continue to Smoke. Re-run routing upsert, then confirm `GET /projects/{project_id}/workflow-definitions/{workflow_id}` before proceeding.
2. If project default chat workflow is wrong, update project settings first, refresh Builder project list, and reopen the release drawer.
3. If Smoke fails with a real `run_id`, open Run Debug immediately, export support bundle, and inspect node failures before any rerun.
4. If release must be reversed, use existing workflow rollback/publish controls, then repeat Bind readback and one bounded smoke run against the rollback version.

## Escalation criteria
1. Escalate when Bind readback and UI state disagree after refresh/reopen.
2. Escalate when Smoke repeatedly fails for the same published version after one controlled rerun.
3. Escalate when support bundle or release report exports omit required identifiers or leak unredacted sensitive data.

## Escalation package checklist
1. Release report JSON.
2. Run Debug support bundle JSON.
3. `workflow_id`, `project_id`, published `version_id`, `run_id`, `correlation_id`.
4. Exact failing stage and timestamp.
