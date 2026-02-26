from __future__ import annotations

import json
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from apps.orchestrator.runtime.env import get_env, load_env


class BridgeConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPBridgeConfig:
    auth_token: Optional[str]
    upstream_call_url: Optional[str]
    upstream_auth_token: Optional[str]
    request_timeout_s: float
    max_timeout_s: float
    max_arguments_bytes: int
    allowed_servers: tuple[str, ...]
    allowed_tools: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "MCPBridgeConfig":
        load_env()
        auth_token_raw = get_env("MCP_BRIDGE_AUTH_TOKEN", "") or ""
        auth_token = auth_token_raw.strip() or None

        upstream_call_url_raw = get_env("MCP_BRIDGE_UPSTREAM_CALL_URL", "") or ""
        upstream_call_url = upstream_call_url_raw.strip() or None

        upstream_auth_token_raw = get_env("MCP_BRIDGE_UPSTREAM_AUTH_TOKEN", "") or ""
        upstream_auth_token = upstream_auth_token_raw.strip() or None

        request_timeout_s = _as_positive_float(get_env("MCP_BRIDGE_UPSTREAM_TIMEOUT_SECONDS", "30"), 30.0)
        max_timeout_s = _as_positive_float(get_env("MCP_BRIDGE_MAX_TIMEOUT_SECONDS", "120"), 120.0)
        max_arguments_bytes = _as_positive_int(get_env("MCP_BRIDGE_MAX_ARGUMENTS_BYTES", str(1024 * 1024)), 1024 * 1024)

        allowed_servers = _parse_csv_values(get_env("MCP_BRIDGE_ALLOWED_SERVERS", ""))
        allowed_tools = _parse_csv_values(get_env("MCP_BRIDGE_ALLOWED_TOOLS", ""))

        return cls(
            auth_token=auth_token,
            upstream_call_url=upstream_call_url,
            upstream_auth_token=upstream_auth_token,
            request_timeout_s=request_timeout_s,
            max_timeout_s=max_timeout_s,
            max_arguments_bytes=max_arguments_bytes,
            allowed_servers=allowed_servers,
            allowed_tools=allowed_tools,
        )


ToolCaller = Callable[
    [str, str, Dict[str, Any], float, Optional[Dict[str, Any]], Optional[Dict[str, Any]]],
    Dict[str, Any] | Awaitable[Dict[str, Any]],
]


def _as_positive_float(raw: Optional[str], default: float) -> float:
    if raw is None:
        return default
    try:
        value = float(raw)
    except Exception:
        return default
    if value <= 0:
        return default
    return value


def _as_positive_int(raw: Optional[str], default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except Exception:
        return default
    if value <= 0:
        return default
    return value


def _parse_csv_values(raw: Optional[str]) -> tuple[str, ...]:
    if not raw:
        return ()
    values: list[str] = []
    for item in raw.split(","):
        candidate = item.strip()
        if candidate:
            values.append(candidate)
    return tuple(values)


def _is_allowed(value: str, allowlist: tuple[str, ...]) -> bool:
    if not allowlist:
        return True
    return value in allowlist


def _build_default_tool_caller(config: MCPBridgeConfig) -> ToolCaller:
    def _call(
        server: str,
        tool: str,
        arguments: Dict[str, Any],
        timeout_s: float,
        auth: Optional[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not config.upstream_call_url:
            raise BridgeConfigError("MCP bridge upstream is not configured; set MCP_BRIDGE_UPSTREAM_CALL_URL")

        headers = {"Content-Type": "application/json"}
        if config.upstream_auth_token:
            headers["Authorization"] = f"Bearer {config.upstream_auth_token}"

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

        with httpx.Client(timeout=config.request_timeout_s) as client:
            response = client.post(config.upstream_call_url, json=payload, headers=headers)

        try:
            body = response.json()
        except Exception as exc:
            raise RuntimeError("MCP bridge upstream returned non-JSON response") from exc

        if response.status_code >= 400:
            message = None
            if isinstance(body, dict):
                error_payload = body.get("error")
                if isinstance(error_payload, dict):
                    message = error_payload.get("message")
            if not isinstance(message, str) or not message.strip():
                message = f"upstream HTTP {response.status_code}"
            raise RuntimeError(f"MCP upstream error: {message}")

        if not isinstance(body, dict):
            raise RuntimeError("MCP bridge upstream response must be an object")
        result = body.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("MCP bridge upstream response must contain object field 'result'")
        return result

    return _call


def create_app(
    config: Optional[MCPBridgeConfig] = None,
    tool_caller: Optional[ToolCaller] = None,
) -> Starlette:
    bridge_config = config or MCPBridgeConfig.from_env()
    caller = tool_caller or _build_default_tool_caller(bridge_config)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "upstream_configured": bool(bridge_config.upstream_call_url),
            }
        )

    async def internal_mcp_call(request: Request) -> JSONResponse:
        if bridge_config.auth_token:
            auth_header = (request.headers.get("Authorization") or "").strip()
            expected = f"Bearer {bridge_config.auth_token}"
            if auth_header != expected:
                return JSONResponse(
                    {"error": {"code": "UNAUTHORIZED", "message": "invalid bridge authorization token"}},
                    status_code=401,
                )

        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                {"error": {"code": "INVALID_ARGUMENT", "message": "request body must be valid JSON"}},
                status_code=400,
            )
        if not isinstance(payload, dict):
            return JSONResponse(
                {"error": {"code": "INVALID_ARGUMENT", "message": "request body must be an object"}},
                status_code=400,
            )

        server_raw = payload.get("server")
        tool_raw = payload.get("tool")
        arguments_raw = payload.get("arguments")
        timeout_raw = payload.get("timeout_s")
        auth_raw = payload.get("auth")
        metadata_raw = payload.get("metadata")

        server = server_raw.strip() if isinstance(server_raw, str) else ""
        tool = tool_raw.strip() if isinstance(tool_raw, str) else ""
        if not server:
            return JSONResponse(
                {"error": {"code": "INVALID_ARGUMENT", "message": "server is required"}},
                status_code=422,
            )
        if not tool:
            return JSONResponse(
                {"error": {"code": "INVALID_ARGUMENT", "message": "tool is required"}},
                status_code=422,
            )
        if not _is_allowed(server, bridge_config.allowed_servers):
            return JSONResponse(
                {"error": {"code": "FORBIDDEN", "message": "server is not allowed"}},
                status_code=403,
            )
        if not _is_allowed(tool, bridge_config.allowed_tools):
            return JSONResponse(
                {"error": {"code": "FORBIDDEN", "message": "tool is not allowed"}},
                status_code=403,
            )

        if arguments_raw is None:
            arguments: Dict[str, Any] = {}
        elif isinstance(arguments_raw, dict):
            arguments = arguments_raw
        else:
            return JSONResponse(
                {"error": {"code": "INVALID_ARGUMENT", "message": "arguments must be an object"}},
                status_code=422,
            )
        serialized_args = json.dumps(arguments)
        if len(serialized_args.encode("utf-8")) > bridge_config.max_arguments_bytes:
            return JSONResponse(
                {"error": {"code": "INVALID_ARGUMENT", "message": "arguments payload is too large"}},
                status_code=422,
            )

        timeout_s = 30.0
        if timeout_raw is not None:
            try:
                timeout_s = float(timeout_raw)
            except Exception:
                return JSONResponse(
                    {"error": {"code": "INVALID_ARGUMENT", "message": "timeout_s must be numeric"}},
                    status_code=422,
                )
        if timeout_s <= 0:
            return JSONResponse(
                {"error": {"code": "INVALID_ARGUMENT", "message": "timeout_s must be > 0"}},
                status_code=422,
            )
        if timeout_s > bridge_config.max_timeout_s:
            return JSONResponse(
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": f"timeout_s exceeds maximum allowed value {bridge_config.max_timeout_s}",
                    }
                },
                status_code=422,
            )

        auth: Optional[Dict[str, Any]] = None
        if auth_raw is not None:
            if not isinstance(auth_raw, dict):
                return JSONResponse(
                    {"error": {"code": "INVALID_ARGUMENT", "message": "auth must be an object"}},
                    status_code=422,
                )
            auth = auth_raw

        metadata: Optional[Dict[str, Any]] = None
        if isinstance(metadata_raw, dict):
            metadata = {}
            for key, value in metadata_raw.items():
                if not isinstance(key, str):
                    continue
                if isinstance(value, str) and value:
                    metadata[key] = value

        try:
            result = caller(server, tool, arguments, timeout_s, auth, metadata)
            if isawaitable(result):
                result = await result
        except BridgeConfigError as exc:
            return JSONResponse(
                {"error": {"code": "PRECONDITION_FAILED", "message": str(exc)}},
                status_code=503,
            )
        except Exception as exc:
            return JSONResponse(
                {"error": {"code": "INTERNAL", "message": str(exc)}},
                status_code=502,
            )

        if not isinstance(result, dict):
            return JSONResponse(
                {"error": {"code": "INTERNAL", "message": "tool caller returned non-object result"}},
                status_code=502,
            )
        return JSONResponse({"result": result})

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/internal/mcp/call", internal_mcp_call, methods=["POST"]),
    ]
    return Starlette(routes=routes)


app = create_app()
