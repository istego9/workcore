---
name: secure-runtime-startup-doctor
description: Diagnose and fix secure-startup failures in local or deployed runtime environments while preserving security guardrails. Use when services fail to start due to missing required env controls, auth gates, CORS policy, or webhook/egress security settings.
---

# Secure Runtime Startup Doctor

## Goal
Restore service startup safely without bypassing core security controls.

## Use when
- API or chat service fails during startup.
- Errors mention required security environment variables.
- Local/docker deployment is blocked by secure defaults.
- Teams need a minimal safe remediation plan.

## Inputs
- Startup error log excerpt.
- Active env profile (`.env`, `.env.docker`, CI vars, cloud app settings).
- Affected services (`orchestrator`, `chatkit`, proxy).
- Expected security posture (dev troubleshooting vs hardened profile).

## Workflow
1. Capture exact failure signal.
- Read logs from:
  - `logs/orchestrator.log`
  - `logs/chatkit.log`
  - `logs/proxy.log`
- Record exact error text and stack location.

2. Map failure to control category.
- Auth gate misconfiguration.
- Webhook signature/secret requirements.
- CORS allowlist requirements.
- Egress policy requirements (for example `INTEGRATION_HTTP_ALLOWED_HOSTS`).

3. Produce minimal safe fix.
- Prefer secure setting values over insecure bypass.
- If bypass is required for local debugging:
  - limit scope to local
  - add explicit expiry note
  - add follow-up task to remove bypass

4. Apply changes to the right layer.
- Local profile files:
  - `.env.example`, `.env.docker.example`, `.env.docker`
- Deployment config/runbooks:
  - `docker-compose.workcore.yml`
  - `docs/deploy/*.md`
  - `docs/runbooks/*.md`

5. Restart and verify.
- Restart services with standard project scripts.
- Verify:
  - `/health` endpoints
  - auth behavior on protected endpoints
  - no security regressions in logs

6. Document remediation.
- Capture root cause, fix, and rollback.
- Include exact env keys changed.

## Diagnostic map (example)
- Error: missing egress allowlist variable.
  - Likely control: secure startup check for integration HTTP.
  - Preferred fix: set allowlist hosts explicitly.
  - Temporary local bypass: only with explicit troubleshooting window.

- Error: unauthorized on startup-dependent checks.
  - Likely control: bearer token or principal header requirements.
  - Preferred fix: align client/server auth config.

## Output template
```md
# Startup Doctor Note

## Symptom
- service:
- error:

## Root cause
- control category:
- missing/misconfigured setting:

## Fix
- changed files/settings:
- secure default preserved: yes/no

## Verification
- health:
- auth checks:
- logs:

## Rollback
- ...

## Follow-up TODOs
- ...
```

## Guardrails
- Never print secrets in notes or examples.
- Never recommend long-term insecure bypass as default.
- Do not alter unrelated security controls to make startup pass.
- If fix confidence is low, stop and ask for exact missing environment context.

## Validation commands
- `./scripts/archctl_validate.sh`
- `./scripts/dev_check.sh`
- targeted pytest checks for affected area when behavior changed

## Done criteria
- Service starts and health checks pass.
- Secure posture is preserved or deviations are explicit and time-bounded.
- Remediation is documented with rollback and TODO follow-up.
