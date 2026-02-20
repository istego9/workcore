from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional

import httpx

from apps.orchestrator.executors.types import EventEmitter, ExecutorResult


@dataclass
class IntegrationHTTPAuthConfig:
    type: str = "none"
    token: Optional[str] = None
    token_env: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    username_env: Optional[str] = None
    password_env: Optional[str] = None


@dataclass
class IntegrationHTTPNodeConfig:
    url: str
    method: str = "GET"
    headers: Dict[str, str] | None = None
    auth: IntegrationHTTPAuthConfig = field(default_factory=IntegrationHTTPAuthConfig)
    timeout_s: float = 10.0
    retry_attempts: int = 0
    retry_backoff_s: float = 0.0
    request_body: Any = None
    fail_on_status: bool = True
    allowed_statuses: Optional[Iterable[int]] = None


class IntegrationHTTPExecutor:
    def __init__(
        self,
        client_factory: Optional[Callable[[float], Any]] = None,
    ) -> None:
        self._client_factory = client_factory or self._default_client

    def __call__(self, run: Any, node: Any, emit: EventEmitter) -> ExecutorResult:
        return self.execute(run, node, emit)

    def execute(self, run: Any, node: Any, emit: EventEmitter) -> ExecutorResult:
        config = self._parse_config(node.config if isinstance(node.config, dict) else {})
        headers: Dict[str, str] = dict(config.headers or {})
        self._apply_auth(headers, config.auth)

        attempts_total = max(0, int(config.retry_attempts)) + 1
        last_error: Optional[Exception] = None

        for attempt in range(1, attempts_total + 1):
            try:
                with self._client_factory(config.timeout_s) as client:
                    response = self._request(client, config, headers)
                payload = self._response_payload(response)
                emit(
                    "integration_http_called",
                    {
                        "method": config.method,
                        "status_code": response.status_code,
                        "attempt": attempt,
                    },
                )
                if self._is_unacceptable_status(response.status_code, config):
                    raise RuntimeError(f"integration_http status {response.status_code} is not allowed")
                return ExecutorResult(output=payload)
            except Exception as exc:  # pragma: no cover - exercised through engine retry behavior
                last_error = exc
                if attempt >= attempts_total:
                    raise
                backoff = max(0.0, float(config.retry_backoff_s or 0.0))
                if backoff > 0:
                    time.sleep(backoff * attempt)

        raise RuntimeError(str(last_error) if last_error else "integration_http request failed")

    @staticmethod
    def _default_client(timeout_s: float) -> httpx.Client:
        return httpx.Client(timeout=timeout_s)

    @staticmethod
    def _request(client: Any, config: IntegrationHTTPNodeConfig, headers: Dict[str, str]) -> Any:
        request_kwargs: Dict[str, Any] = {"headers": headers}
        if config.request_body is not None:
            request_kwargs["json"] = config.request_body
        return client.request(config.method, config.url, **request_kwargs)

    @staticmethod
    def _parse_config(config: Dict[str, Any]) -> IntegrationHTTPNodeConfig:
        url_raw = config.get("url")
        url = url_raw.strip() if isinstance(url_raw, str) else ""
        if not url:
            raise RuntimeError("integration_http requires non-empty config.url")

        method_raw = config.get("method")
        method = method_raw.strip().upper() if isinstance(method_raw, str) and method_raw.strip() else "GET"
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise RuntimeError("integration_http method must be one of GET, POST, PUT, PATCH, DELETE")

        headers_raw = config.get("headers")
        headers: Dict[str, str] = {}
        if headers_raw is not None:
            if not isinstance(headers_raw, dict):
                raise RuntimeError("integration_http headers must be an object")
            for key, value in headers_raw.items():
                if not isinstance(key, str) or not key:
                    continue
                if value is None:
                    continue
                headers[key] = str(value)

        auth_raw = config.get("auth")
        auth = IntegrationHTTPAuthConfig()
        if auth_raw is not None:
            if not isinstance(auth_raw, dict):
                raise RuntimeError("integration_http auth must be an object")
            auth = IntegrationHTTPAuthConfig(
                type=str(auth_raw.get("type") or "none").strip().lower(),
                token=str(auth_raw.get("token")).strip() if isinstance(auth_raw.get("token"), str) else None,
                token_env=(
                    str(auth_raw.get("token_env")).strip() if isinstance(auth_raw.get("token_env"), str) else None
                ),
                username=str(auth_raw.get("username")).strip() if isinstance(auth_raw.get("username"), str) else None,
                password=str(auth_raw.get("password")).strip() if isinstance(auth_raw.get("password"), str) else None,
                username_env=(
                    str(auth_raw.get("username_env")).strip()
                    if isinstance(auth_raw.get("username_env"), str)
                    else None
                ),
                password_env=(
                    str(auth_raw.get("password_env")).strip()
                    if isinstance(auth_raw.get("password_env"), str)
                    else None
                ),
            )

        timeout_raw = config.get("timeout_s")
        timeout_s = 10.0
        if timeout_raw is not None:
            try:
                timeout_s = float(timeout_raw)
            except Exception as exc:  # pragma: no cover - guarded by runtime validation
                raise RuntimeError("integration_http timeout_s must be numeric") from exc
            if timeout_s <= 0:
                raise RuntimeError("integration_http timeout_s must be > 0")

        retry_attempts_raw = config.get("retry_attempts")
        retry_attempts = 0
        if retry_attempts_raw is not None:
            try:
                retry_attempts = int(retry_attempts_raw)
            except Exception as exc:
                raise RuntimeError("integration_http retry_attempts must be an integer") from exc
            if retry_attempts < 0:
                raise RuntimeError("integration_http retry_attempts must be >= 0")

        retry_backoff_raw = config.get("retry_backoff_s")
        retry_backoff_s = 0.0
        if retry_backoff_raw is not None:
            try:
                retry_backoff_s = float(retry_backoff_raw)
            except Exception as exc:
                raise RuntimeError("integration_http retry_backoff_s must be numeric") from exc
            if retry_backoff_s < 0:
                raise RuntimeError("integration_http retry_backoff_s must be >= 0")

        fail_on_status_raw = config.get("fail_on_status")
        fail_on_status = True if fail_on_status_raw is None else bool(fail_on_status_raw)

        allowed_statuses_raw = config.get("allowed_statuses")
        allowed_statuses: Optional[list[int]] = None
        if allowed_statuses_raw is not None:
            if not isinstance(allowed_statuses_raw, list):
                raise RuntimeError("integration_http allowed_statuses must be an array")
            allowed_statuses = []
            for status_raw in allowed_statuses_raw:
                try:
                    status = int(status_raw)
                except Exception as exc:
                    raise RuntimeError("integration_http allowed_statuses must contain integers") from exc
                if status < 100 or status > 599:
                    raise RuntimeError("integration_http allowed_statuses must contain valid HTTP status codes")
                allowed_statuses.append(status)

        return IntegrationHTTPNodeConfig(
            url=url,
            method=method,
            headers=headers,
            auth=auth,
            timeout_s=timeout_s,
            retry_attempts=retry_attempts,
            retry_backoff_s=retry_backoff_s,
            request_body=config.get("request_body"),
            fail_on_status=fail_on_status,
            allowed_statuses=allowed_statuses,
        )

    @staticmethod
    def _apply_auth(headers: Dict[str, str], auth: IntegrationHTTPAuthConfig) -> None:
        auth_type = (auth.type or "none").strip().lower()
        if auth_type in {"", "none"}:
            return
        if auth_type == "bearer":
            token = auth.token or _load_env(auth.token_env)
            if not token:
                raise RuntimeError("integration_http bearer auth requires token or token_env")
            headers["Authorization"] = f"Bearer {token}"
            return
        if auth_type == "basic":
            username = auth.username or _load_env(auth.username_env)
            password = auth.password or _load_env(auth.password_env)
            if username is None or password is None:
                raise RuntimeError("integration_http basic auth requires username/password")
            raw = f"{username}:{password}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('ascii')}"
            return
        raise RuntimeError("integration_http auth.type must be one of: none, bearer, basic")

    @staticmethod
    def _response_payload(response: Any) -> Dict[str, Any]:
        body: Any
        text = response.text
        try:
            body = response.json()
        except Exception:
            body = text
        return {
            "status_code": int(response.status_code),
            "headers": dict(response.headers),
            "body": body,
        }

    @staticmethod
    def _is_unacceptable_status(status_code: int, config: IntegrationHTTPNodeConfig) -> bool:
        if config.allowed_statuses:
            return status_code not in set(config.allowed_statuses)
        if not config.fail_on_status:
            return False
        return status_code < 200 or status_code >= 300


def _load_env(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None
