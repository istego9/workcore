from __future__ import annotations

import base64
import ipaddress
import os
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional, Sequence
from urllib.parse import urlparse

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


@dataclass(frozen=True)
class IntegrationHTTPEgressPolicy:
    allowed_hosts: Sequence[str] = ()
    allowed_schemes: Sequence[str] = ("https",)
    allow_private_networks: bool = False
    deny_cidrs: Sequence[ipaddress._BaseNetwork] = ()
    host_resolver: Optional[Callable[[str], Sequence[str]]] = None

    @classmethod
    def from_env(
        cls,
        env_getter: Optional[Callable[[str, Optional[str]], Optional[str]]] = None,
    ) -> "IntegrationHTTPEgressPolicy":
        getter = env_getter or (lambda name, default=None: os.getenv(name, default))
        allowed_hosts = tuple(
            _normalize_host_rule(item)
            for item in str(getter("INTEGRATION_HTTP_ALLOWED_HOSTS", "") or "").split(",")
            if _normalize_host_rule(item)
        )
        allowed_schemes = tuple(
            _normalize_scheme(item)
            for item in str(getter("INTEGRATION_HTTP_ALLOWED_SCHEMES", "https") or "").split(",")
            if _normalize_scheme(item)
        )
        allow_private_networks = _parse_bool(
            getter("INTEGRATION_HTTP_ALLOW_PRIVATE_NETWORKS", "0"),
            default=False,
        )
        deny_cidrs = _load_cidr_rules(getter("INTEGRATION_HTTP_DENY_CIDRS", "") or "")
        return cls(
            allowed_hosts=allowed_hosts,
            allowed_schemes=allowed_schemes or ("https",),
            allow_private_networks=allow_private_networks,
            deny_cidrs=deny_cidrs,
        )

    def validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").strip().lower()
        host = (parsed.hostname or "").strip().lower()
        if not scheme or scheme not in {item.lower() for item in self.allowed_schemes}:
            allowed = ", ".join(sorted({item.lower() for item in self.allowed_schemes}))
            raise RuntimeError(
                f"integration_http URL scheme '{scheme or '<empty>'}' is not allowed; allowed schemes: {allowed}"
            )
        if not host:
            raise RuntimeError("integration_http URL must include hostname")
        if not self.allowed_hosts:
            raise RuntimeError(
                "integration_http egress allowlist is empty; set INTEGRATION_HTTP_ALLOWED_HOSTS"
            )
        if not any(_host_matches_rule(host, rule) for rule in self.allowed_hosts):
            raise RuntimeError(
                f"integration_http target host '{host}' is not allowed by INTEGRATION_HTTP_ALLOWED_HOSTS"
            )
        if not self.allow_private_networks and _is_private_or_local_host(host):
            raise RuntimeError(
                f"integration_http target host '{host}' is blocked by private-network policy"
            )
        resolved_ips = _resolve_host_ips(host, resolver=self.host_resolver)
        if not resolved_ips:
            raise RuntimeError(f"integration_http target host '{host}' could not be resolved")
        for ip_raw in resolved_ips:
            ip_value = _parse_ip(ip_raw)
            if ip_value is None:
                raise RuntimeError(
                    f"integration_http DNS resolution for host '{host}' returned non-IP value '{ip_raw}'"
                )
            if _matches_cidrs(ip_value, self.deny_cidrs):
                raise RuntimeError(
                    f"integration_http target host '{host}' resolved to blocked CIDR address '{ip_value}'"
                )
            if not self.allow_private_networks and _is_private_or_local_ip(ip_value):
                raise RuntimeError(
                    f"integration_http target host '{host}' resolved to private/local address '{ip_value}'"
                )


class IntegrationHTTPExecutor:
    def __init__(
        self,
        client_factory: Optional[Callable[[float], Any]] = None,
        egress_policy: Optional[IntegrationHTTPEgressPolicy] = None,
    ) -> None:
        self._client_factory = client_factory or self._default_client
        self._egress_policy = egress_policy or IntegrationHTTPEgressPolicy.from_env()

    def __call__(self, run: Any, node: Any, emit: EventEmitter) -> ExecutorResult:
        return self.execute(run, node, emit)

    def execute(self, run: Any, node: Any, emit: EventEmitter) -> ExecutorResult:
        config = self._parse_config(node.config if isinstance(node.config, dict) else {})
        self._egress_policy.validate_url(config.url)
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


def _normalize_host_rule(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _normalize_scheme(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _host_matches_rule(host: str, rule: str) -> bool:
    normalized_host = host.strip().lower()
    normalized_rule = rule.strip().lower()
    if not normalized_host or not normalized_rule:
        return False
    if normalized_rule == normalized_host:
        return True
    if normalized_rule.startswith("*."):
        suffix = normalized_rule[2:]
        return normalized_host.endswith(f".{suffix}") and normalized_host != suffix
    return False


def _is_private_or_local_host(host: str) -> bool:
    normalized = host.strip().lower()
    if not normalized:
        return True
    if normalized in {"localhost", "0.0.0.0"}:
        return True
    if normalized.endswith(".localhost") or normalized.endswith(".local") or normalized.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return _is_private_or_local_ip(ip)


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _is_private_or_local_ip(ip: ipaddress._BaseAddress) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _load_cidr_rules(raw_value: str) -> Sequence[ipaddress._BaseNetwork]:
    rules = []
    for raw_item in str(raw_value or "").split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            rules.append(ipaddress.ip_network(item, strict=False))
        except ValueError as exc:
            raise RuntimeError(
                f"INTEGRATION_HTTP_DENY_CIDRS contains invalid CIDR value '{item}'"
            ) from exc
    return tuple(rules)


def _resolve_host_ips(
    host: str,
    resolver: Optional[Callable[[str], Sequence[str]]] = None,
) -> Sequence[str]:
    ip_literal = _parse_ip(host)
    if ip_literal is not None:
        return (str(ip_literal),)
    resolve = resolver or _default_host_resolver
    resolved = resolve(host)
    unique = []
    seen = set()
    for value in resolved:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return tuple(unique)


def _default_host_resolver(host: str) -> Sequence[str]:
    try:
        results = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RuntimeError(f"integration_http target host '{host}' could not be resolved") from exc
    addresses = []
    for result in results:
        if len(result) < 5:
            continue
        sockaddr = result[4]
        if not isinstance(sockaddr, tuple) or not sockaddr:
            continue
        address = str(sockaddr[0]).strip()
        if address:
            addresses.append(address)
    return tuple(addresses)


def _parse_ip(value: str) -> Optional[ipaddress._BaseAddress]:
    try:
        return ipaddress.ip_address(str(value).strip())
    except ValueError:
        return None


def _matches_cidrs(ip: ipaddress._BaseAddress, cidrs: Sequence[ipaddress._BaseNetwork]) -> bool:
    for cidr in cidrs:
        if ip.version != cidr.version:
            continue
        if ip in cidr:
            return True
    return False
