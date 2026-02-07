from __future__ import annotations

from typing import Any, Dict

from apps.orchestrator.api.workflow_store import WorkflowRecord, WorkflowSummary, WorkflowVersionRecord

from apps.orchestrator.runtime.models import Interrupt, Run


def run_to_dict(run: Run) -> Dict[str, Any]:
    metadata = dict(run.metadata or {})
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
        "node_runs": [
            {
                "node_id": node_id,
                "status": node_run.status,
                "attempt": node_run.attempt,
                "output": node_run.output,
                "last_error": node_run.last_error,
                "trace_id": node_run.trace_id,
                "usage": node_run.usage,
            }
            for node_id, node_run in run.node_runs.items()
        ],
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
