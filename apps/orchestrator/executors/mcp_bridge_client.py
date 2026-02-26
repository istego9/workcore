from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import httpx

from apps.orchestrator.runtime.env import get_env


def _as_positive_float(value: Optional[str], default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except Exception:
        return default
    if parsed <= 0:
        return default
    return parsed


def _as_positive_int(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except Exception:
        return default
    if parsed <= 0:
        return default
    return parsed


@dataclass(frozen=True)
class MCPBridgeClientConfig:
    base_url: str
    auth_token: Optional[str] = None
    request_timeout_s: float = 30.0
    max_response_bytes: int = 2 * 1024 * 1024


class UnconfiguredMCPClient:
    def call_tool(
        self,
        server: str,
        tool: str,
        arguments: Dict[str, Any],
        timeout_s: float,
        auth: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise RuntimeError("MCP bridge is not configured; set MCP_BRIDGE_BASE_URL")


class MCPBridgeHttpClient:
    def __init__(
        self,
        config: MCPBridgeClientConfig,
        client_factory: Optional[Callable[[float], Any]] = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory or (lambda timeout_s: httpx.Client(timeout=timeout_s))

    def call_tool(
        self,
        server: str,
        tool: str,
        arguments: Dict[str, Any],
        timeout_s: float,
        auth: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "server": server,
            "tool": tool,
            "arguments": arguments,
            "timeout_s": timeout_s,
        }
        if isinstance(auth, dict) and auth:
            payload["auth"] = auth
        if isinstance(metadata, dict) and metadata:
            payload["metadata"] = metadata

        headers = {"Content-Type": "application/json"}
        if self._config.auth_token:
            headers["Authorization"] = f"Bearer {self._config.auth_token}"

        base_url = self._config.base_url.rstrip("/")
        endpoint = f"{base_url}/internal/mcp/call"
        try:
            with self._client_factory(self._config.request_timeout_s) as client:
                response = client.post(endpoint, json=payload, headers=headers)
        except Exception as exc:
            raise RuntimeError(f"MCP bridge request failed: {exc}") from exc

        content = response.content or b""
        if len(content) > self._config.max_response_bytes:
            raise RuntimeError("MCP bridge response exceeds max allowed size")

        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError("MCP bridge returned non-JSON response") from exc

        if response.status_code >= 400:
            message = None
            if isinstance(data, dict):
                error_payload = data.get("error")
                if isinstance(error_payload, dict):
                    message = error_payload.get("message")
            if not isinstance(message, str) or not message.strip():
                message = f"bridge HTTP {response.status_code}"
            raise RuntimeError(f"MCP bridge error: {message}")

        if not isinstance(data, dict):
            raise RuntimeError("MCP bridge response must be an object")
        result = data.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("MCP bridge response is missing object field 'result'")
        return result


def mcp_client_from_env(
    env_getter: Optional[Callable[[str, Optional[str]], Optional[str]]] = None,
) -> MCPBridgeHttpClient | UnconfiguredMCPClient:
    getter = env_getter or (lambda name, default=None: get_env(name, default))
    base_url_raw = getter("MCP_BRIDGE_BASE_URL", "") or ""
    base_url = base_url_raw.strip()
    if not base_url:
        return UnconfiguredMCPClient()

    auth_token_raw = getter("MCP_BRIDGE_AUTH_TOKEN", "")
    auth_token = auth_token_raw.strip() if isinstance(auth_token_raw, str) and auth_token_raw.strip() else None

    timeout_s = _as_positive_float(getter("MCP_BRIDGE_REQUEST_TIMEOUT_SECONDS", "30"), default=30.0)
    max_response_bytes = _as_positive_int(getter("MCP_BRIDGE_MAX_RESPONSE_BYTES", str(2 * 1024 * 1024)), default=2 * 1024 * 1024)

    return MCPBridgeHttpClient(
        config=MCPBridgeClientConfig(
            base_url=base_url,
            auth_token=auth_token,
            request_timeout_s=timeout_s,
            max_response_bytes=max_response_bytes,
        )
    )
