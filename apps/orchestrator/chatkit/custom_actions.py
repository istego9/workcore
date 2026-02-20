from __future__ import annotations

from typing import Any, Dict, Optional


CANONICAL_ACTION_TYPES = {
    "interrupt.approve",
    "interrupt.reject",
    "interrupt.submit",
    "interrupt.cancel",
}

_ACTION_ALIAS_MAP = {
    "interrupt.approve": {
        "interrupt.approve",
        "approve",
        "approval.approve",
        "interrupt_approve",
    },
    "interrupt.reject": {
        "interrupt.reject",
        "reject",
        "approval.reject",
        "interrupt_reject",
    },
    "interrupt.submit": {
        "interrupt.submit",
        "submit",
        "interaction.submit",
        "interrupt_submit",
    },
    "interrupt.cancel": {
        "interrupt.cancel",
        "cancel",
        "interaction.cancel",
        "interrupt_cancel",
    },
}

ALIAS_TO_CANONICAL_ACTION_TYPE = {
    alias: canonical
    for canonical, aliases in _ACTION_ALIAS_MAP.items()
    for alias in aliases
}


def resolve_canonical_action_type(action_type: Any, payload: Optional[Dict[str, Any]] = None) -> Optional[str]:
    candidates: list[str] = []
    if isinstance(payload, dict):
        payload_action_type = payload.get("action_type")
        if isinstance(payload_action_type, str) and payload_action_type.strip():
            candidates.append(payload_action_type)
        payload_type = payload.get("type")
        if isinstance(payload_type, str) and payload_type.strip():
            candidates.append(payload_type)
    if isinstance(action_type, str) and action_type.strip():
        candidates.append(action_type)

    for raw in candidates:
        normalized = raw.strip().lower()
        resolved = ALIAS_TO_CANONICAL_ACTION_TYPE.get(normalized)
        if resolved:
            return resolved
    return None
