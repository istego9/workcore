---
name: chatkit-widgets-actions
description: Build ChatKit widgets and actions for interactive workflow steps (approval, forms, file uploads, resume/cancel). Use when implementing interaction/approval nodes or action handlers.
---

# ChatKit Widgets and Actions

## Widget principles
- Represent a single interrupt state per widget.
- Ensure actions are idempotent (retries happen).
- Show clear state transitions: pending -> submitted -> completed/failed.

## Steps
1) Define widget types:
   - Approval widget (approve/reject)
   - Form widget (JSON schema-driven if available)
   - File upload widget (with constraints)
2) Define action payloads:
   - run_id, interrupt_id, action_type
   - Input fields and file references
   - Client-generated idempotency key
3) Implement action handlers:
   - Validate signature/auth
   - Resume interrupt in orchestrator
   - Stream updated status back into the chat
4) Add tests:
   - Action handler validates payload
   - Action triggers run continuation
   - Widget state updates properly

## Definition of done
- Approval and file upload are supported end-to-end.
- Duplicate action submissions do not create duplicate resumes.
- Errors are displayed clearly and can be retried safely.
