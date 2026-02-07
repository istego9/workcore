---
name: chatkit-server
description: Implement the ChatKit advanced integration server: sessions, threads, message streaming, and mapping chat events to workflow runs. Use when building server-side ChatKit integration or wiring chat to runs/interrupts.
---

# ChatKit Server

## Responsibilities
- Create/manage ChatKit sessions and threads.
- Route user messages to start runs or resume interrupts.
- Stream runtime progress into chat as messages and/or widgets.

## Steps
1) Establish the mapping:
   - chat_session_id <-> (tenant_id, user_id)
   - chat_thread_id <-> run_id (or run group)
2) Implement message handling:
   - Parse intent (start run, continue run, answer interrupt)
   - Call orchestrator APIs accordingly
3) Implement streaming bridge:
   - Subscribe to run SSE stream
   - Translate runtime events into chat outputs
4) Add security:
   - Auth for session creation
   - Server-side OpenAI API keys only (no client-side secrets)

## Definition of done
- A user can start a run from chat.
- Runtime progress is visible in the chat.
- Interrupts are represented and can be resumed from chat flow.
