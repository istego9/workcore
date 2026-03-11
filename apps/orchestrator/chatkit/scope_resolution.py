from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


CHAT_RESOLUTION_MODE_EXPLICIT_WORKFLOW = "explicit_workflow"
CHAT_RESOLUTION_MODE_PROJECT_DEFAULT = "project_default"
CHAT_RESOLUTION_MODE_HEADER_DEFAULT = "header_default"
CHAT_RESOLUTION_MODE_ERROR = "error"


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


@dataclass(frozen=True)
class ResolvedChatThreadScope:
    workflow_id: str
    workflow_version_id: str | None
    project_id: str | None
    mode: str


class ChatThreadResolutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        *,
        details: Any = None,
        project_id: str | None = None,
        workflow_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        self.project_id = project_id
        self.workflow_id = workflow_id


ProjectDefaultWorkflowResolver = Callable[[str, str], Awaitable[tuple[str, str | None]]]


async def resolve_thread_create_scope(
    metadata: dict[str, Any],
    header_project_id: str | None,
    tenant_id: str,
    resolve_project_default_workflow: ProjectDefaultWorkflowResolver,
) -> ResolvedChatThreadScope:
    explicit_workflow_id = _normalize_text(metadata.get("workflow_id"))
    explicit_version_id = _normalize_text(metadata.get("workflow_version_id"))
    metadata_project_id = _normalize_text(metadata.get("project_id"))
    header_project_scope = _normalize_text(header_project_id)

    if explicit_workflow_id:
        project_id = metadata_project_id or header_project_scope or None
        return ResolvedChatThreadScope(
            workflow_id=explicit_workflow_id,
            workflow_version_id=explicit_version_id or None,
            project_id=project_id,
            mode=CHAT_RESOLUTION_MODE_EXPLICIT_WORKFLOW,
        )

    project_id = metadata_project_id or header_project_scope
    if not project_id:
        raise ChatThreadResolutionError(
            "CHAT_PROJECT_SCOPE_REQUIRED",
            "metadata.project_id or X-Project-Id is required when metadata.workflow_id is omitted",
            422,
        )

    workflow_id, workflow_version_id = await resolve_project_default_workflow(project_id, tenant_id)
    return ResolvedChatThreadScope(
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        project_id=project_id,
        mode=(
            CHAT_RESOLUTION_MODE_PROJECT_DEFAULT
            if metadata_project_id
            else CHAT_RESOLUTION_MODE_HEADER_DEFAULT
        ),
    )
