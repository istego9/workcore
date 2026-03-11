# ADR-0012: Project-Centric Chat Thread Resolution

Date: 2026-03-11
Status: Accepted

## Context
Public chat is exposed through the canonical `POST /chat` endpoint, with deprecated alias
`POST /chatkit` preserved during a sunset window. Existing ChatKit clients start threads with
`metadata.workflow_id`, but the broader platform already treats `project_id` as the external
entry scope and `workflow_id` as a direct override.

This mismatch creates avoidable friction for project-scoped chat integrations and forces clients
to know workflow internals even when a project already owns the chat experience.

## Decision
Adopt project-centric thread creation for public chat while preserving explicit workflow mode.

Resolution order for `threads.create`:
1. `metadata.workflow_id` -> explicit workflow mode
2. else `metadata.project_id` -> resolve `projects.settings.default_chat_workflow_id`
3. else `X-Project-Id` -> resolve `projects.settings.default_chat_workflow_id`
4. else return `CHAT_PROJECT_SCOPE_REQUIRED`

Project defaults are stored additively in `projects.settings.default_chat_workflow_id`.
No new public chat endpoint or dedicated ChatKit config table is introduced.

## Compatibility strategy
- Additive only.
- Existing clients that already pass `metadata.workflow_id` continue unchanged.
- `/chatkit` keeps full behavior parity with `/chat` during the deprecation window, including
  deprecation headers and typed error envelopes.

## Consequences
- External clients can start project-scoped chat threads without knowing workflow IDs.
- Project admins gain a single place to configure which published workflow serves public chat.
- Chat runtime must validate default workflow presence/published status at request time and emit
  stable error codes:
  - `CHAT_PROJECT_SCOPE_REQUIRED`
  - `CHAT_DEFAULT_WORKFLOW_NOT_CONFIGURED`
  - `CHAT_DEFAULT_WORKFLOW_NOT_FOUND`

## Risks and mitigations
- Risk: stale project settings point at unpublished or removed workflows.
  - Mitigation: resolve against tenant/project-scoped published workflow state on every `threads.create`.
- Risk: alias drift between `/chat` and `/chatkit`.
  - Mitigation: keep shared resolution logic in the ChatKit service/app and parity tests for success and errors.
- Risk: observability gaps during mixed direct/project resolution.
  - Mitigation: persist resolved project/workflow metadata on threads and log `chat_resolution_mode`.
