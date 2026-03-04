# Chat Endpoint Cutover Notice (2026-03-04)

Use this message for all external integration teams.

## Pre-cutover message

Subject: WorkCore Chat endpoint migration today: `/chatkit` -> `/chat`

Hello team,

Today (March 4, 2026) we are migrating the public chat endpoint path on the WorkCore API gateway.

What changes:
- Chat endpoint path changes from `POST /chatkit` to `POST /chat`.
- The API hosts remain the same:
  - `https://api.runwcr.com`
  - `https://api.hq21.tech`
- Request payload contract is unchanged:
  - `threads.create`
  - `threads.add_user_message`
  - `threads.custom_action`
  - `input.transcribe`

What does not change:
- Orchestrator flow remains unchanged:
  - `POST /orchestrator/messages`
  - `GET /runs/{run_id}/stream`
  - interrupt resume/cancel endpoints

Auth profiles supported:
- Single bearer profile:
  - one token for both `/orchestrator/*` and `/chat`.
- Split bearer profile:
  - `/orchestrator/*` token and `/chat` token are different.

Action required on your side:
1. Replace `/chatkit` with `/chat` in all client integrations.
2. Keep sending `X-Tenant-Id`.
3. Verify bearer token profile (single vs split) for your tenant/environment.

Validation examples:
```bash
# should return 200 + SSE
curl -N -X POST "https://api.runwcr.com/chat" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "X-Tenant-Id: local" \
  -H "Content-Type: application/json" \
  -d '{"type":"threads.create","metadata":{"workflow_id":"wf_example"},"params":{"input":{"content":[{"type":"input_text","text":"start"}],"attachments":[]}}}'

# after cutover should return 404
curl -i -X POST "https://api.runwcr.com/chatkit" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "X-Tenant-Id: local" \
  -H "Content-Type: application/json" \
  -d '{"type":"threads.create","metadata":{"workflow_id":"wf_example"},"params":{"input":{"content":[{"type":"input_text","text":"start"}],"attachments":[]}}}'
```

If you still see errors, send:
- UTC timestamp
- host + path + method
- `X-Correlation-Id`
- response status + response body

Regards,  
WorkCore Platform

## Integrator curl pack (copy/paste)

Use these checks to validate migration in production.

```bash
export BASE_URL="https://api.hq21.tech"   # or https://api.runwcr.com
export TENANT_ID="local"
export PROJECT_ID="<project_id>"
export WORKFLOW_ID="<workflow_id>"
export WORKCORE_API_TOKEN="<WORKCORE_API_AUTH_TOKEN>"
export CHATKIT_TOKEN="<CHATKIT_AUTH_TOKEN>" # required only for split bearer profile
```

Single bearer profile:
```bash
# 1) orchestrator path (auth + routing path)
curl -i -X POST "$BASE_URL/orchestrator/messages" \
  -H "Authorization: Bearer $WORKCORE_API_TOKEN" \
  -H "X-Tenant-Id: $TENANT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id":"'"$PROJECT_ID"'",
    "message":{"text":"ping from integrator"}
  }'

# 2) chat path (new canonical endpoint)
curl -N -X POST "$BASE_URL/chat" \
  -H "Authorization: Bearer $WORKCORE_API_TOKEN" \
  -H "X-Tenant-Id: $TENANT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "type":"threads.create",
    "metadata":{"workflow_id":"'"$WORKFLOW_ID"'"},
    "params":{"input":{"content":[{"type":"input_text","text":"start"}],"attachments":[]}}
  }'
```

Split bearer profile:
```bash
# 1) orchestrator path uses WORKCORE API token
curl -i -X POST "$BASE_URL/orchestrator/messages" \
  -H "Authorization: Bearer $WORKCORE_API_TOKEN" \
  -H "X-Tenant-Id: $TENANT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id":"'"$PROJECT_ID"'",
    "message":{"text":"ping from integrator"}
  }'

# 2) chat path uses CHATKIT token
curl -N -X POST "$BASE_URL/chat" \
  -H "Authorization: Bearer $CHATKIT_TOKEN" \
  -H "X-Tenant-Id: $TENANT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "type":"threads.create",
    "metadata":{"workflow_id":"'"$WORKFLOW_ID"'"},
    "params":{"input":{"content":[{"type":"input_text","text":"start"}],"attachments":[]}}
  }'
```

Deprecated endpoint check:
```bash
# after cutover this path must not be used by integrations
curl -i -X POST "$BASE_URL/chatkit" \
  -H "Authorization: Bearer ${CHATKIT_TOKEN:-$WORKCORE_API_TOKEN}" \
  -H "X-Tenant-Id: $TENANT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "type":"threads.create",
    "metadata":{"workflow_id":"'"$WORKFLOW_ID"'"},
    "params":{"input":{"content":[{"type":"input_text","text":"start"}],"attachments":[]}}
  }'
```

Expected outcomes:
- `/orchestrator/messages`: request is authorized (business-level `4xx` like `ERR_PROJECT_NOT_FOUND` is possible with test payloads).
- `/chat`: request is authorized and processed by Chat transport (SSE stream).
- `/chatkit`: deprecated; integrations must migrate to `/chat`.

## Post-cutover message

Subject: WorkCore chat cutover completed: use `POST /chat`

Hello team,

Cutover is complete as of March 4, 2026.

- Canonical chat endpoint: `POST /chat`
- Deprecated endpoint: `POST /chatkit` now returns `404`
- Hosts:
  - `https://api.runwcr.com`
  - `https://api.hq21.tech`

If your integration still calls `/chatkit`, please migrate immediately to `/chat`.

Regards,  
WorkCore Platform
