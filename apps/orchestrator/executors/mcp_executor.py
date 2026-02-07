from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Protocol

from apps.orchestrator.executors.types import EventEmitter, ExecutorResult


class MCPClient(Protocol):
    def call_tool(
        self,
        server: str,
        tool: str,
        arguments: Dict[str, Any],
        timeout_s: float,
        auth: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ...


@dataclass
class MCPNodeConfig:
    server: str
    tool: str
    arguments: Dict[str, Any]
    timeout_s: float = 30
    auth: Optional[Dict[str, Any]] = None
    allowed_tools: Optional[Iterable[str]] = None


class MCPExecutor:
    def __init__(self, client: MCPClient) -> None:
        self.client = client

    def execute(self, config: MCPNodeConfig, emit: EventEmitter) -> ExecutorResult:
        if config.allowed_tools and config.tool not in config.allowed_tools:
            raise RuntimeError("MCP tool not in allowlist")
        response = self.client.call_tool(
            server=config.server,
            tool=config.tool,
            arguments=config.arguments,
            timeout_s=config.timeout_s,
            auth=config.auth,
        )
        emit("tool_called", {"tool": config.tool, "server": config.server})
        return ExecutorResult(output=response, raw_output=response)
