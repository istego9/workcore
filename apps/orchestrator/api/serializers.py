from __future__ import annotations

import json
import math
from typing import Any, Dict

from apps.orchestrator.api.workflow_store import WorkflowRecord, WorkflowSummary, WorkflowVersionRecord

from apps.orchestrator.runtime.models import Interrupt, Run


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def _estimate_tokens(value: Any) -> int:
    text = _to_text(value)
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def _backfill_mock_usage(node_output: Any) -> Dict[str, Any] | None:
    if not isinstance(node_output, dict):
        return None
    if node_output.get("mock") is not True:
        return None
    input_tokens = _estimate_tokens(node_output.get("resolved_instructions")) + _estimate_tokens(
        node_output.get("resolved_input")
    )
    output_tokens = _estimate_tokens(node_output)
    return {
        "provider": "mock",
        "estimated": True,
        "requests": 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    }


def run_to_dict(run: Run) -> Dict[str, Any]:
    metadata = dict(run.metadata or {})
    node_runs = []
    for node_id, node_run in run.node_runs.items():
        usage = node_run.usage
        if not isinstance(usage, dict):
            usage = _backfill_mock_usage(node_run.output)
        node_runs.append(
            {
                "node_id": node_id,
                "status": node_run.status,
                "attempt": node_run.attempt,
                "output": node_run.output,
                "last_error": node_run.last_error,
                "trace_id": node_run.trace_id,
                "usage": usage,
            }
        )
    return {
        "run_id": run.id,
        "workflow_id": run.workflow_id,
        "version_id": run.version_id,
        "status": run.status,
        "mode": run.mode,
        "inputs": run.inputs,
        "state": run.state,
        "outputs": run.outputs,
        "metadata": metadata,
        "correlation_id": metadata.get("correlation_id"),
        "trace_id": metadata.get("trace_id"),
        "tenant_id": metadata.get("tenant_id"),
        "project_id": metadata.get("project_id"),
        "import_run_id": metadata.get("import_run_id"),
        "created_at": metadata.get("created_at"),
        "updated_at": metadata.get("updated_at"),
        "node_runs": node_runs,
    }


def interrupt_to_dict(interrupt: Interrupt) -> Dict[str, Any]:
    return {
        "interrupt_id": interrupt.id,
        "run_id": interrupt.run_id,
        "node_id": interrupt.node_id,
        "type": interrupt.type,
        "status": interrupt.status,
        "prompt": interrupt.prompt,
        "input_schema": interrupt.input_schema,
        "allow_file_upload": interrupt.allow_file_upload,
        "input": interrupt.input,
        "files": interrupt.files,
    }


def workflow_to_dict(workflow: WorkflowRecord) -> Dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "name": workflow.name,
        "description": workflow.description,
        "draft": workflow.draft,
        "active_version_id": workflow.active_version_id,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
    }


def workflow_summary_to_dict(workflow: WorkflowSummary) -> Dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "name": workflow.name,
        "description": workflow.description,
        "active_version_id": workflow.active_version_id,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
    }


def workflow_version_to_dict(version: WorkflowVersionRecord) -> Dict[str, Any]:
    return {
        "version_id": version.version_id,
        "workflow_id": version.workflow_id,
        "version_number": version.version_number,
        "hash": version.hash,
        "content": version.content,
        "created_at": version.created_at.isoformat(),
    }
