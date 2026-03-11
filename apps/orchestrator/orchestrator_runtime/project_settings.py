from __future__ import annotations

from typing import Any, Mapping

DEFAULT_CHAT_WORKFLOW_ID_KEY = "default_chat_workflow_id"


def normalize_project_settings(settings: Any) -> dict[str, Any]:
    if settings is None:
        return {}
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    normalized = dict(settings)
    if DEFAULT_CHAT_WORKFLOW_ID_KEY in normalized:
        raw = normalized.get(DEFAULT_CHAT_WORKFLOW_ID_KEY)
        if raw is None:
            normalized[DEFAULT_CHAT_WORKFLOW_ID_KEY] = None
        elif not isinstance(raw, str) or not raw.strip():
            raise ValueError("settings.default_chat_workflow_id must be a non-empty string or null")
        else:
            normalized[DEFAULT_CHAT_WORKFLOW_ID_KEY] = raw.strip()
    return normalized


def merge_project_settings(
    current: Mapping[str, Any] | None,
    patch: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(current or {})
    if patch:
        merged.update(dict(patch))
    return merged


def get_default_chat_workflow_id(settings: Mapping[str, Any] | None) -> str | None:
    if not isinstance(settings, Mapping):
        return None
    raw = settings.get(DEFAULT_CHAT_WORKFLOW_ID_KEY)
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    normalized = raw.strip()
    return normalized or None
