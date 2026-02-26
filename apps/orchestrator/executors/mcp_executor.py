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
        metadata: Optional[Dict[str, Any]] = None,
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

    def __call__(self, run: Any, node: Any, emit: EventEmitter) -> ExecutorResult:
        config = self._parse_node_config(node.config if isinstance(node.config, dict) else {})
        metadata = self._build_metadata(run, node)
        return self.execute(config, emit, metadata=metadata)

    def execute(
        self,
        config: MCPNodeConfig,
        emit: EventEmitter,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutorResult:
        if config.allowed_tools and config.tool not in config.allowed_tools:
            raise RuntimeError("MCP tool not in allowlist")
        response = self.client.call_tool(
            server=config.server,
            tool=config.tool,
            arguments=config.arguments,
            timeout_s=config.timeout_s,
            auth=config.auth,
            metadata=metadata,
        )
        emit("tool_called", {"tool": config.tool, "server": config.server})
        return ExecutorResult(output=response, raw_output=response)

    @staticmethod
    def _parse_node_config(config: Dict[str, Any]) -> MCPNodeConfig:
        server_raw = config.get("server")
        server = server_raw.strip() if isinstance(server_raw, str) else ""
        if not server:
            raise RuntimeError("MCP config.server is required")

        tool_raw = config.get("tool")
        tool = tool_raw.strip() if isinstance(tool_raw, str) else ""
        if not tool:
            raise RuntimeError("MCP config.tool is required")

        arguments_raw = config.get("arguments")
        if arguments_raw is None:
            arguments = {}
        elif isinstance(arguments_raw, dict):
            arguments = arguments_raw
        else:
            raise RuntimeError("MCP config.arguments must be an object")

        timeout_raw = config.get("timeout_s")
        timeout_s = 30.0
        if timeout_raw is not None:
            try:
                timeout_s = float(timeout_raw)
            except Exception as exc:
                raise RuntimeError("MCP config.timeout_s must be numeric") from exc
            if timeout_s <= 0:
                raise RuntimeError("MCP config.timeout_s must be > 0")

        auth_raw = config.get("auth")
        auth: Optional[Dict[str, Any]] = None
        if auth_raw is not None:
            if not isinstance(auth_raw, dict):
                raise RuntimeError("MCP config.auth must be an object")
            auth = auth_raw

        allowed_tools_raw = config.get("allowed_tools")
        allowed_tools: Optional[Iterable[str]] = None
        if allowed_tools_raw is not None:
            if not isinstance(allowed_tools_raw, list):
                raise RuntimeError("MCP config.allowed_tools must be an array")
            parsed: list[str] = []
            for item in allowed_tools_raw:
                if not isinstance(item, str):
                    continue
                candidate = item.strip()
                if candidate:
                    parsed.append(candidate)
            allowed_tools = parsed

        return MCPNodeConfig(
            server=server,
            tool=tool,
            arguments=arguments,
            timeout_s=timeout_s,
            auth=auth,
            allowed_tools=allowed_tools,
        )

    @staticmethod
    def _build_metadata(run: Any, node: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        run_id = getattr(run, "id", None)
        node_id = getattr(node, "id", None)
        if isinstance(run_id, str) and run_id:
            payload["run_id"] = run_id
        if isinstance(node_id, str) and node_id:
            payload["node_id"] = node_id

        metadata = getattr(run, "metadata", None)
        if isinstance(metadata, dict):
            for key in ("tenant_id", "project_id", "correlation_id", "trace_id"):
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    payload[key] = value
        return payload
