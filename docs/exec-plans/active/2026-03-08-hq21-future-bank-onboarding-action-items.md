# HQ21 Future Bank Onboarding Action Items

## Classification
- E: external integration behavior change

## 1) Goal and scope
- Register partner tenant `hq21-future-bank` in the existing APIM partner onboarding flow.
- Generate the standard onboarding ZIP package with partner credentials and connection instructions.

## 2) Spec files to update
- None. No public contract or payload change.

## 3) Compatibility strategy
- Additive only.
- Reuse existing OAuth audience, partner map structure, and onboarding package format.

## 4) Implementation files
- `deploy/azure/config/partners.yaml`

## 5) Tests
- `bash -n deploy/azure/scripts/apim_partner_onboard.sh`
- `bash -n deploy/azure/scripts/deploy_apim.sh`
- `bash -n deploy/azure/scripts/deploy_frontdoor.sh`
- `bash -n deploy/azure/scripts/apim_partner_rotate_secret.sh`
- `bash -n deploy/azure/scripts/apim_partner_revoke.sh`

## 6) Observability/security impacts
- Do not print or commit generated client secrets.
- Keep partner mapping additive in APIM.
- Use the standard onboarding ZIP format with secret delivery warnings.

## 7) Rollout/rollback notes
- Rollout: add partner config, run onboarding automation, verify package generation.
- Rollback: revoke partner app via existing revoke script and remove partner config entry if onboarding must be cancelled.

## 8) Outstanding TODOs/questions
- TODO: deliver the generated ZIP over the approved secure channel only.
