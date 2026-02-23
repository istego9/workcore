# Quality Score

## Purpose
This scoreboard keeps quality visible and comparable across major WorkCore areas.
It is an operational artifact for planning and reviews, not a replacement for tests.

## Scoring model
- `0`: Missing
- `1`: Partial or manually verified
- `2`: Automated coverage exists but gaps are known
- `3`: Stable and regression-resistant (automated checks, metrics, and clear ownership)

## Update policy
1. Update affected rows in each A-E change (see task classes in `AGENTS.md`).
2. Include evidence in PR notes:
   - tests and checks executed
   - docs/spec updates
   - observability/security deltas
3. Keep scores honest. If confidence is low, reduce score and add action items.

## Scoreboard
| Area | Tests | Contracts/Validation | Docs | Observability | Security | Overall | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| API + Schemas | TBD | TBD | TBD | TBD | TBD | TBD | OpenAPI + JSON schema ownership |
| Runtime + Executors | TBD | TBD | TBD | TBD | TBD | TBD | Orchestrator execution semantics |
| Streaming (SSE) | TBD | TBD | TBD | TBD | TBD | TBD | Snapshot/replay and reconnect behavior |
| ChatKit integration | TBD | TBD | TBD | TBD | TBD | TBD | Widgets/actions and idempotency |
| Webhooks | TBD | TBD | TBD | TBD | TBD | TBD | Signature validation and delivery behavior |
| Builder UI | TBD | TBD | TBD | TBD | TBD | TBD | Unit + E2E stability |
| Security posture | TBD | TBD | TBD | TBD | TBD | TBD | See `docs/SECURITY.md` |
| Reliability posture | TBD | TBD | TBD | TBD | TBD | TBD | See `docs/RELIABILITY.md` |

## Review cadence
- Minimum: update on each meaningful behavior change.
- Recommended: weekly quality pass that converts repeated TODOs into planned work under `docs/exec-plans/`.
