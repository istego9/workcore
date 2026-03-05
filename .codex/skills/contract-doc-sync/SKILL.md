---
name: contract-doc-sync
description: Keep API contracts and integration documentation synchronized across OpenAPI, API reference, and external integration guides. Use when endpoint paths, auth, headers, payloads, or error contracts change.
---

# Contract Doc Sync

## Goal
Eliminate contract drift between specification files and integration-facing documentation.

## Use when
- Any changes touch:
  - `docs/api/openapi.yaml`
  - `docs/api/schemas/*.json`
  - `docs/api/reference.md`
  - `docs/integration/*.md`
  - generated docs: `docs/integration/*.html`, `docs/integration/*.pdf`
- API host/path/auth guidance changes (for example `/chat` vs `/chatkit`, OAuth flow, required headers).
- You are preparing release notes or cutover communication.

## Source-of-truth order
1. `docs/api/openapi.yaml`
2. `docs/api/schemas/*.json`
3. `docs/api/reference.md`
4. `docs/integration/*.md`
5. `docs/integration/*.html` and `docs/integration/*.pdf` (derived artifacts)

If a higher-priority source conflicts with a lower one, fix the lower one.

## Workflow
1. Build a change map.
- Extract changed contract units:
  - endpoints and methods
  - required headers
  - auth scheme
  - request/response fields
  - error envelopes and statuses

2. Run mismatch scan.
- Use `rg` to locate stale tokens across docs:
  - old paths (`/chatkit`)
  - old auth examples (`WORKCORE_API_AUTH_TOKEN` vs OAuth access token)
  - old host/mode wording
- Build a mismatch table with file + line + expected value.

3. Update docs in order.
- Update `reference.md` first.
- Update integration markdown docs next.
- Update generated html/pdf or regenerate from the updated markdown source.
- If regeneration tooling is unavailable, mark generated files as stale with explicit `TODO`.

4. Validate consistency.
- Confirm the same canonical values appear across all docs:
  - endpoint path
  - auth instructions
  - required headers
  - error examples
  - deprecation notes

5. Ensure changelog coverage.
- If public contract changed, ensure `CHANGELOG.md` includes:
  - previous API version
  - current API version
  - Added/Changed/Deprecated/Removed deltas

6. Run validation checks.
- `./scripts/archctl_validate.sh`
- Any area-specific tests impacted by the contract update.

## Output template
```md
# Contract Sync Report

## Scope
- Contract files:
- Docs files:

## Mismatch matrix
- file:line | stale value | expected value | status

## Updated artifacts
- ...

## Residual TODOs
- ...

## Verification
- Commands:
- Results:
```

## Guardrails
- Do not invent fields, endpoints, or status codes.
- Do not edit derived docs without updating their markdown source when source exists.
- Never claim generated html/pdf are current unless regenerated in this run.
- If uncertainty exists, leave an explicit `TODO` and request clarification.

## Done criteria
- No unresolved P0 mismatches.
- OpenAPI/reference/integration guides agree on path/auth/header semantics.
- Changelog is updated when public contract changed.
