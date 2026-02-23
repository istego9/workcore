from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from apps.orchestrator.project_router.custom_actions import normalize_orchestrator_custom_action_payload
from apps.orchestrator.orchestrator_runtime.store import (
    OrchestrationStore,
    OrchestratorConfigRecord,
    ProjectRecord,
    WorkflowDefinitionRecord,
)


@dataclass
class RoutingRequest:
    session_id: str
    user_id: str
    project_id: str
    orchestrator_id: Optional[str]
    workflow_id: Optional[str]
    message_id: str
    message_text: str
    metadata: Dict[str, Any]
    message_type: str = "threads.add_user_message"
    action_type: Optional[str] = None
    action_payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "RoutingRequest":
        if not isinstance(payload, dict):
            raise ProjectRouterError("INVALID_ARGUMENT", "request body must be an object", 400)
        session_id = payload.get("session_id")
        user_id = payload.get("user_id")
        project_id = payload.get("project_id")
        orchestrator_id = payload.get("orchestrator_id")
        workflow_id = payload.get("workflow_id")
        message = payload.get("message")
        metadata = payload.get("metadata")

        if not isinstance(session_id, str) or not session_id.strip():
            raise ProjectRouterError("INVALID_ARGUMENT", "session_id is required", 400)
        if not isinstance(user_id, str) or not user_id.strip():
            raise ProjectRouterError("INVALID_ARGUMENT", "user_id is required", 400)
        if not isinstance(project_id, str) or not project_id.strip():
            raise ProjectRouterError("ERR_PROJECT_ID_REQUIRED", "project_id is required", 422)
        if orchestrator_id is not None and (not isinstance(orchestrator_id, str) or not orchestrator_id.strip()):
            raise ProjectRouterError("INVALID_ARGUMENT", "orchestrator_id must be a non-empty string or null", 400)
        if workflow_id is not None and (not isinstance(workflow_id, str) or not workflow_id.strip()):
            raise ProjectRouterError("INVALID_ARGUMENT", "workflow_id must be a non-empty string or null", 400)
        if not isinstance(message, dict):
            raise ProjectRouterError("INVALID_ARGUMENT", "message object is required", 400)
        message_id = message.get("id")
        message_text = message.get("text")
        message_type_raw = message.get("type")
        message_payload_raw = message.get("payload")
        if not isinstance(message_id, str) or not message_id.strip():
            raise ProjectRouterError("INVALID_ARGUMENT", "message.id is required", 400)
        if not isinstance(message_text, str) or not message_text.strip():
            raise ProjectRouterError("INVALID_ARGUMENT", "message.text is required", 400)
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ProjectRouterError("INVALID_ARGUMENT", "metadata must be an object", 400)
        if message_type_raw is None:
            message_type = "threads.add_user_message"
        elif isinstance(message_type_raw, str) and message_type_raw.strip():
            message_type = message_type_raw.strip().lower()
        else:
            raise ProjectRouterError(
                "INVALID_ARGUMENT",
                "message.type must be a non-empty string when provided",
                400,
            )

        action_type: Optional[str] = None
        action_payload: Dict[str, Any] = {}
        if message_type == "threads.custom_action":
            if message_payload_raw is None:
                message_payload_raw = {}
            if not isinstance(message_payload_raw, dict):
                raise ProjectRouterError(
                    "INVALID_ARGUMENT",
                    "message.payload must be an object for threads.custom_action",
                    400,
                )
            action_type = message_text.strip()
            try:
                action_payload = normalize_orchestrator_custom_action_payload(message_payload_raw)
            except ValueError as exc:
                raise ProjectRouterError("INVALID_ARGUMENT", str(exc), 400) from exc
        elif message_payload_raw is not None and not isinstance(message_payload_raw, dict):
            raise ProjectRouterError("INVALID_ARGUMENT", "message.payload must be an object when provided", 400)

        return cls(
            session_id=session_id.strip(),
            user_id=user_id.strip(),
            project_id=project_id.strip(),
            orchestrator_id=orchestrator_id.strip() if isinstance(orchestrator_id, str) else None,
            workflow_id=workflow_id.strip() if isinstance(workflow_id, str) else None,
            message_id=message_id.strip(),
            message_text=message_text.strip(),
            metadata=dict(metadata),
            message_type=message_type,
            action_type=action_type,
            action_payload=action_payload,
        )


@dataclass
class ProjectRoute:
    mode: str
    project: ProjectRecord
    orchestrator: Optional[OrchestratorConfigRecord]
    workflow_definition: Optional[WorkflowDefinitionRecord]


class ProjectRouterError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ProjectRouter:
    def __init__(self, store: OrchestrationStore) -> None:
        self.store = store

    async def resolve(self, request: RoutingRequest, tenant_id: str) -> ProjectRoute:
        project = await self.store.get_project(request.project_id, tenant_id=tenant_id)
        if project is None:
            raise ProjectRouterError("ERR_PROJECT_NOT_FOUND", "project not found", 404)

        if request.workflow_id:
            workflow_definition = await self.store.get_workflow_definition(
                request.project_id,
                request.workflow_id,
                tenant_id=tenant_id,
            )
            if workflow_definition is None:
                raise ProjectRouterError(
                    "ERR_WORKFLOW_NOT_IN_PROJECT",
                    "workflow is not registered in project",
                    409,
                )
            if not workflow_definition.active:
                raise ProjectRouterError(
                    "ERR_WORKFLOW_NOT_IN_PROJECT",
                    "workflow is not active in project",
                    409,
                )
            return ProjectRoute(
                mode="direct",
                project=project,
                orchestrator=None,
                workflow_definition=workflow_definition,
            )

        orchestrator_id = request.orchestrator_id or project.default_orchestrator_id
        if not orchestrator_id:
            configs = await self.store.list_orchestrator_configs(request.project_id, tenant_id=tenant_id)
            if configs:
                orchestrator_id = configs[0].orchestrator_id
        if not orchestrator_id:
            raise ProjectRouterError(
                "ERR_ORCHESTRATOR_NOT_IN_PROJECT",
                "orchestrator is not configured for project",
                409,
            )

        orchestrator = await self.store.get_orchestrator_config(
            request.project_id,
            orchestrator_id,
            tenant_id=tenant_id,
        )
        if orchestrator is None:
            raise ProjectRouterError(
                "ERR_ORCHESTRATOR_NOT_IN_PROJECT",
                "orchestrator does not belong to project",
                409,
            )
        return ProjectRoute(
            mode="orchestrated",
            project=project,
            orchestrator=orchestrator,
            workflow_definition=None,
        )
