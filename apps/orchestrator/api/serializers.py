from __future__ import annotations

import json
import math
from typing import Any, Dict

from apps.orchestrator.api.capability_store import CapabilityRecord
from apps.orchestrator.api.handoff_store import HandoffPackageRecord
from apps.orchestrator.api.ledger_store import RunLedgerEntry
from apps.orchestrator.api.workflow_store import WorkflowRecord, WorkflowSummary, WorkflowVersionRecord
from apps.orchestrator.orchestrator_runtime import (
    OrchestratorConfigRecord,
    ProjectRecord,
    WorkflowDefinitionRecord,
)

from apps.orchestrator.runtime.models import Interrupt, Run
from apps.orchestrator.runtime.projection import project_run_payload_for_transport


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
    projected_state, projected_outputs = project_run_payload_for_transport(run.state, run.outputs, metadata)
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
        "resolved_version": metadata.get("resolved_version") or run.version_id,
        "status": run.status,
        "mode": run.mode,
        "inputs": run.inputs,
        "state": projected_state,
        "outputs": projected_outputs,
        "metadata": metadata,
        "correlation_id": metadata.get("correlation_id"),
        "trace_id": metadata.get("trace_id"),
        "tenant_id": metadata.get("tenant_id"),
        "project_id": metadata.get("project_id"),
        "session_id": metadata.get("session_id"),
        "import_run_id": metadata.get("import_run_id"),
        "cancellable": bool(metadata.get("cancellable", run.status in {"RUNNING", "WAITING_FOR_INPUT"})),
        "commit_point_reached": metadata.get("commit_point_reached"),
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


def project_to_dict(project: ProjectRecord) -> Dict[str, Any]:
    return {
        "project_id": project.project_id,
        "project_name": project.project_name,
        "tenant_id": project.tenant_id,
        "default_orchestrator_id": project.default_orchestrator_id,
        "settings": project.settings,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def orchestrator_config_to_dict(config: OrchestratorConfigRecord) -> Dict[str, Any]:
    return {
        "project_id": config.project_id,
        "orchestrator_id": config.orchestrator_id,
        "name": config.name,
        "routing_policy": config.routing_policy,
        "fallback_workflow_id": config.fallback_workflow_id,
        "prompt_profile": config.prompt_profile,
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat(),
    }


def workflow_definition_to_dict(definition: WorkflowDefinitionRecord) -> Dict[str, Any]:
    return {
        "project_id": definition.project_id,
        "workflow_id": definition.workflow_id,
        "name": definition.name,
        "description": definition.description,
        "tags": definition.tags,
        "examples": definition.examples,
        "active": definition.active,
        "is_fallback": definition.is_fallback,
        "created_at": definition.created_at.isoformat(),
        "updated_at": definition.updated_at.isoformat(),
    }


def workflow_to_dict(workflow: WorkflowRecord) -> Dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "project_id": workflow.project_id,
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
        "project_id": workflow.project_id,
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


def capability_to_dict(capability: CapabilityRecord) -> Dict[str, Any]:
    return {
        "capability_id": capability.capability_id,
        "version": capability.version,
        "node_type": capability.node_type,
        "contract": capability.contract,
        "created_at": capability.created_at.isoformat(),
    }


def run_ledger_entry_to_dict(entry: RunLedgerEntry) -> Dict[str, Any]:
    return {
        "ledger_id": entry.ledger_id,
        "run_id": entry.run_id,
        "workflow_id": entry.workflow_id,
        "version_id": entry.version_id,
        "step_id": entry.step_id,
        "capability_id": entry.capability_id,
        "capability_version": entry.capability_version,
        "status": entry.status,
        "event_type": entry.event_type,
        "decision": entry.decision,
        "artifacts": entry.artifacts,
        "payload": entry.payload,
        "timestamp": entry.timestamp.isoformat(),
    }


def handoff_to_dict(record: HandoffPackageRecord) -> Dict[str, Any]:
    return {
        "handoff_id": record.handoff_id,
        "workflow_id": record.workflow_id,
        "version_id": record.version_id,
        "run_id": record.run_id,
        "replay_mode": record.replay_mode,
        "status": record.status,
        "package": {
            "context": record.context,
            "constraints": record.constraints,
            "expected_result": record.expected_result,
            "acceptance_checks": record.acceptance_checks,
        },
        "metadata": record.metadata,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }
