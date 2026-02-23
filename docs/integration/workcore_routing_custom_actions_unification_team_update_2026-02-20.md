# Team Update Draft: WorkCore Routing + Custom Actions Unification

Date: 2026-02-20
Owner: WorkCore / Orchestrator
Audience: Team that requested routing + custom actions unification

## Subject
WorkCore: реализованы доработки по унификации routing и `custom_action` (P0/P1/P2), нужен финальный API sync

## Email body (RU)
Коллеги, привет.

Закрыли запрос по выносу routing/custom actions логики в WorkCore и унификации orchestration слоя. Ниже сводка по статусу.

Сделано:
- P0:
  - Нативная поддержка `threads.custom_action` в runtime с canonical `action_type` + alias map.
  - Универсальный context API: `POST /orchestrator/context/get|set|unset` с персистом на уровне оркестратора.
  - Интеграционная HTTP-нода (`integration_http`) с auth headers, timeout/retry и маппингом ответа в state.
  - Profile-подобный паттерн реализован внутри workflow: context + integration node + prefill без backend-спецкейса.
- P1:
  - Нативная нормализация payload для `custom_action` (flatten wrapper fields, scalar typing, `documents` passthrough, validation projection paths).
  - `decision_trace` в ответе оркестратора (`/orchestrator/messages`): кандидаты, score, выбранный workflow/action, причина.
  - Стандартизированный error contract через `action_error`.
- P2:
  - Политики маршрутизации: `sticky`, `allow_switch`, `explicit_switch_only`, `cooldown_seconds`, `hysteresis_margin`.
  - Anti-flip/hysteresis логика для снижения переключений между близкими сценариями.
  - Offline replay/eval endpoint: `POST /orchestrator/eval/replay` с per-case результатами и aggregate metrics.

Ожидаемый целевой результат из запроса достигнут:
- backend больше не должен держать локальный intent/router/prefill слой;
- message routing и context hydration вынесены в WorkCore;
- custom actions проходят end-to-end через WorkCore;
- маршрутизация прозрачна и дебажится через `decision_trace`.

Контракт и версия API:
- OpenAPI: `0.16.0` (последовательные additive изменения `0.11.0 -> 0.16.0`).
- Спека/доки/чейнджлог обновлены.
- Миграции для routing context и runtime-расширений добавлены.

Валидация:
- `./scripts/archctl_validate.sh` — pass
- `./.venv/bin/python -m pytest apps/orchestrator/tests` — pass (`160 passed`)
- `./scripts/dev_check.sh` — pass

PR:
- https://github.com/istego9/workcore/pull/1

Предлагаю синхрон по финальному API-контракту и rollout-плану по этапам P0/P1/P2 (30 минут), чтобы зафиксировать:
- deprecation timeline backend обходов;
- порядок включения policy knobs (`cooldown/hysteresis`) в проде;
- формат и использование replay/eval в регулярной валидации routing quality.

Спасибо.

## Suggested send format
- Can be sent as-is via email/Slack.
- Optionally attach PR link and latest OpenAPI diff from `CHANGELOG.md`.
