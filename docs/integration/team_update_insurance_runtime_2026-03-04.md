# Team Update Draft: Insurance Classification + Azure Runtime

Date: March 4, 2026

## Subject
`[WorkCore] Insurance classification восстановлен в primary Azure (api.hq21.tech)`

## Email body
Коллеги, привет.

Краткий апдейт по падениям insurance classification в WorkCore runtime.

Что было:
- 3 марта 2026 в `proj_insurance_20260216`, workflow `wf_f265975e` (`uw_doc_classification_v1`) фиксировались `FAILED` run:
  - `run_5aac9635` (`wfv_9e756aa9`)
  - `run_21eb46e4` (`wfv_be0794c7`)
- Причина: `classify_docs` падал с `400 BadRequest` из Azure OpenAI:
  - Responses API требует `api-version >= 2025-03-01-preview`.

Что сделано:
- Обновлен `AZURE_OPENAI_API_VERSION` до `2025-03-01-preview` в runtime (Key Vault + container apps).
- В деплой-конфигурации зафиксирован тот же default, чтобы последующие деплои не откатывали версию.
- Обновлены deployment/integration docs (gateway alias и диагностика FAILED run).

Проверка после фикса:
- Контрольные rerun по тем же версиям завершились успешно:
  - `run_c3c4c643` (`wfv_9e756aa9`) -> `COMPLETED`
  - `run_d58c16ee` (`wfv_be0794c7`) -> `COMPLETED`
- По `wf_f265975e` новые run стабильно `COMPLETED`, `classify_docs=RESOLVED`.

Важно по gateway:
- `api.runwcr.com` рассматриваем как alias того же gateway/backend, не как отдельный runtime режим.

Если нужно, могу отдельно выслать короткий checklist для on-call: preflight -> deploy -> insurance verification -> rollback.

