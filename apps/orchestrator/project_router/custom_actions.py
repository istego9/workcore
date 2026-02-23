from __future__ import annotations

import re
from typing import Any, Dict

from apps.orchestrator.runtime.projection import normalize_projection_paths


_PAYLOAD_WRAPPER_KEYS = {"input", "form", "form_data", "fields"}
_PAYLOAD_SYSTEM_KEYS = {
    "action_type",
    "type",
    "run_id",
    "interrupt_id",
    "files",
    "idempotency_key",
    "action_id",
}

_INT_RE = re.compile(r"^-?(0|[1-9][0-9]*)$")
_FLOAT_RE = re.compile(r"^-?(0|[1-9][0-9]*)\.[0-9]+$")


def normalize_orchestrator_custom_action_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("message.payload must be an object for threads.custom_action")

    extracted: Dict[str, Any] = {}
    for key in _PAYLOAD_WRAPPER_KEYS:
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            extracted.update(_normalize_mapping(candidate))

    if extracted:
        for key, value in payload.items():
            if key in _PAYLOAD_SYSTEM_KEYS or key in _PAYLOAD_WRAPPER_KEYS:
                continue
            extracted.setdefault(key, _normalize_value(value))
        normalized = extracted
    else:
        normalized = {
            key: _normalize_value(value)
            for key, value in payload.items()
            if key not in _PAYLOAD_SYSTEM_KEYS
        }

    _normalize_projection_controls(normalized)
    return normalized


def _normalize_mapping(value: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, item in value.items():
        if key in _PAYLOAD_WRAPPER_KEYS and isinstance(item, dict):
            normalized.update(_normalize_mapping(item))
            continue
        if key == "documents":
            normalized[key] = item
            continue
        normalized[key] = _normalize_value(item)
    return normalized


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, str):
        return _coerce_scalar(value)
    return value


def _coerce_scalar(value: str) -> Any:
    trimmed = value.strip()
    lowered = trimmed.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if _INT_RE.match(trimmed):
        try:
            return int(trimmed)
        except ValueError:
            return value
    if _FLOAT_RE.match(trimmed):
        try:
            return float(trimmed)
        except ValueError:
            return value
    return value


def _normalize_projection_controls(normalized: Dict[str, Any]) -> None:
    state_paths = normalized.get("state_exclude_paths")
    if state_paths is not None:
        normalized["state_exclude_paths"] = normalize_projection_paths(
            state_paths,
            field_name="state_exclude_paths",
        )
    output_paths = normalized.get("output_include_paths")
    if output_paths is not None:
        normalized["output_include_paths"] = normalize_projection_paths(
            output_paths,
            field_name="output_include_paths",
        )
