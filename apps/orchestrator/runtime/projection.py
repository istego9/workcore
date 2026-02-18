from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Mapping, Sequence, Tuple


STATE_EXCLUDE_PATHS_KEY = "state_exclude_paths"
OUTPUT_INCLUDE_PATHS_KEY = "output_include_paths"

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_MISSING = object()
_DELETE = object()


def is_valid_projection_path(path: str) -> bool:
    if not isinstance(path, str):
        return False
    candidate = path.strip()
    if not candidate:
        return False
    segments = candidate.split(".")
    for segment in segments:
        if not segment:
            return False
        if segment == "*":
            continue
        if not _SEGMENT_RE.fullmatch(segment):
            return False
    return True


def normalize_projection_paths(value: Any, *, field_name: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array of strings")

    normalized: List[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field_name}[{idx}] must be a string")
        candidate = item.strip()
        if not is_valid_projection_path(candidate):
            raise ValueError(f"{field_name}[{idx}] is not a valid path")
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def projection_paths_from_metadata(metadata: Mapping[str, Any] | None) -> Tuple[List[str], List[str]]:
    if not isinstance(metadata, Mapping):
        return [], []

    state_raw = metadata.get(STATE_EXCLUDE_PATHS_KEY)
    output_raw = metadata.get(OUTPUT_INCLUDE_PATHS_KEY)

    state_paths = _safe_paths(state_raw)
    output_paths = _safe_paths(output_raw)
    return state_paths, output_paths


def project_run_payload_for_transport(
    state: Any,
    outputs: Any,
    metadata: Mapping[str, Any] | None,
) -> Tuple[Any, Any]:
    state_paths, output_paths = projection_paths_from_metadata(metadata)
    projected_state = apply_state_exclude_paths(state, state_paths)
    projected_outputs = apply_output_include_paths(outputs, output_paths)
    return projected_state, projected_outputs


def apply_state_exclude_paths(state: Any, exclude_paths: Sequence[str]) -> Any:
    projected = copy.deepcopy(state)
    for raw_path in exclude_paths:
        if not is_valid_projection_path(raw_path):
            continue
        segments = raw_path.split(".")
        projected = _exclude_path(projected, segments)
        if projected is _DELETE:
            projected = {}
            break
    return projected


def apply_output_include_paths(outputs: Any, include_paths: Sequence[str]) -> Any:
    if outputs is None:
        return None
    if not include_paths:
        return copy.deepcopy(outputs)

    merged: Any = _MISSING
    for raw_path in include_paths:
        if not is_valid_projection_path(raw_path):
            continue
        selected = _select_path(outputs, raw_path.split("."))
        if selected is _MISSING:
            continue
        merged = _merge(merged, selected)

    if merged is _MISSING:
        return {} if isinstance(outputs, dict) else None
    return merged


def _safe_paths(value: Any) -> List[str]:
    try:
        return normalize_projection_paths(value, field_name="projection_paths")
    except ValueError:
        return []


def _exclude_path(value: Any, segments: Sequence[str]) -> Any:
    if not segments:
        return _DELETE

    segment = segments[0]
    rest = segments[1:]

    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            if segment == "*" or key == segment:
                projected_item = _exclude_path(item, rest)
                if projected_item is _DELETE:
                    continue
                result[key] = projected_item
            else:
                result[key] = copy.deepcopy(item)
        return result

    if isinstance(value, list):
        result: List[Any] = []
        if segment == "*":
            for item in value:
                projected_item = _exclude_path(item, rest)
                if projected_item is _DELETE:
                    continue
                result.append(projected_item)
            return result

        for item in value:
            projected_item = _exclude_path(item, segments)
            if projected_item is _DELETE:
                result.append(copy.deepcopy(item))
            else:
                result.append(projected_item)
        return result

    return copy.deepcopy(value)


def _select_path(value: Any, segments: Sequence[str]) -> Any:
    if not segments:
        return copy.deepcopy(value)

    segment = segments[0]
    rest = segments[1:]

    if isinstance(value, dict):
        if segment == "*":
            result: Dict[str, Any] = {}
            for key, item in value.items():
                selected = _select_path(item, rest)
                if selected is _MISSING:
                    continue
                result[key] = selected
            return result if result else _MISSING
        if segment not in value:
            return _MISSING
        selected = _select_path(value[segment], rest)
        if selected is _MISSING:
            return _MISSING
        return {segment: selected}

    if isinstance(value, list):
        if segment == "*":
            selected_items = []
            for item in value:
                selected = _select_path(item, rest)
                if selected is _MISSING:
                    continue
                selected_items.append(selected)
            return selected_items if selected_items else _MISSING

        selected_items = []
        for item in value:
            selected = _select_path(item, segments)
            if selected is _MISSING:
                continue
            selected_items.append(selected)
        return selected_items if selected_items else _MISSING

    return _MISSING


def _merge(left: Any, right: Any) -> Any:
    if left is _MISSING:
        return copy.deepcopy(right)

    if isinstance(left, dict) and isinstance(right, dict):
        merged: Dict[str, Any] = copy.deepcopy(left)
        for key, value in right.items():
            if key in merged:
                merged[key] = _merge(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged

    if isinstance(left, list) and isinstance(right, list):
        max_len = max(len(left), len(right))
        merged_list: List[Any] = []
        for idx in range(max_len):
            left_exists = idx < len(left)
            right_exists = idx < len(right)
            if left_exists and right_exists:
                merged_list.append(_merge(left[idx], right[idx]))
            elif left_exists:
                merged_list.append(copy.deepcopy(left[idx]))
            else:
                merged_list.append(copy.deepcopy(right[idx]))
        return merged_list

    return copy.deepcopy(right)
