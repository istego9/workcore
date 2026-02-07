from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

import httpx


@dataclass
class WorkCoreApiError(RuntimeError):
    code: str
    message: str
    status_code: int
    correlation_id: Optional[str] = None
    details: Any = None

    def __str__(self) -> str:  # pragma: no cover - trivial repr formatting
        base = f"{self.code} ({self.status_code}): {self.message}"
        if self.correlation_id:
            return f"{base} [correlation_id={self.correlation_id}]"
        return base


class WorkCoreClient:
    def __init__(
        self,
        base_url: str,
        bearer_token: Optional[str] = None,
        timeout_s: float = 30.0,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_s)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "WorkCoreClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @staticmethod
    def _new_correlation_id() -> str:
        return f"corr_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _new_trace_id() -> str:
        return f"trace_{uuid.uuid4().hex[:12]}"

    def _headers(
        self,
        *,
        tenant_id: str,
        correlation_id: Optional[str],
        trace_id: Optional[str],
        idempotency_key: Optional[str],
        last_event_id: Optional[str] = None,
    ) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Tenant-Id": tenant_id,
            "X-Correlation-Id": correlation_id or self._new_correlation_id(),
            "X-Trace-Id": trace_id or self._new_trace_id(),
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        tenant_id: str,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        headers = self._headers(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
        )
        response = self._client.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            json=payload,
        )
        response_payload: Dict[str, Any] = {}
        if response.content:
            try:
                parsed = response.json()
                if isinstance(parsed, dict):
                    response_payload = parsed
            except Exception:
                response_payload = {}
        if response.is_success:
            return response_payload

        error = response_payload.get("error") if isinstance(response_payload, dict) else None
        code = error.get("code") if isinstance(error, dict) else "INTERNAL"
        message = error.get("message") if isinstance(error, dict) else response.text
        details = error.get("details") if isinstance(error, dict) else None
        raise WorkCoreApiError(
            code=str(code),
            message=str(message),
            status_code=response.status_code,
            correlation_id=response_payload.get("correlation_id"),
            details=details,
        )

    def start_run(
        self,
        workflow_id: str,
        *,
        tenant_id: str,
        project_id: str,
        import_run_id: str,
        inputs: Dict[str, Any],
        version_id: Optional[str] = None,
        mode: str = "async",
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload_metadata = dict(metadata or {})
        payload_metadata.setdefault("tenant_id", tenant_id)
        payload_metadata.setdefault("project_id", project_id)
        payload_metadata.setdefault("import_run_id", import_run_id)
        payload_metadata.setdefault("trace_id", trace_id or self._new_trace_id())
        if correlation_id:
            payload_metadata.setdefault("correlation_id", correlation_id)

        payload = {
            "inputs": inputs,
            "mode": mode,
            "metadata": payload_metadata,
        }
        if version_id:
            payload["version_id"] = version_id
        return self._request_json(
            "POST",
            f"/workflows/{workflow_id}/runs",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    def get_run(
        self,
        run_id: str,
        *,
        tenant_id: str,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request_json(
            "GET",
            f"/runs/{run_id}",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

    def resume_interrupt(
        self,
        run_id: str,
        interrupt_id: str,
        *,
        tenant_id: str,
        input_data: Optional[Dict[str, Any]] = None,
        files: Optional[list[Dict[str, Any]]] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request_json(
            "POST",
            f"/runs/{run_id}/interrupts/{interrupt_id}/resume",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            payload={"input": input_data or {}, "files": files or []},
        )

    def cancel_run(
        self,
        run_id: str,
        *,
        tenant_id: str,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request_json(
            "POST",
            f"/runs/{run_id}/cancel",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
        )

    def rerun_node(
        self,
        run_id: str,
        node_id: str,
        *,
        scope: str,
        tenant_id: str,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request_json(
            "POST",
            f"/runs/{run_id}/rerun-node",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            payload={"node_id": node_id, "scope": scope},
        )

    def stream_run_events(
        self,
        run_id: str,
        *,
        tenant_id: str,
        last_event_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        headers = self._headers(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            idempotency_key=None,
            last_event_id=last_event_id,
        )
        with self._client.stream(
            "GET",
            f"{self.base_url}/runs/{run_id}/stream",
            headers=headers,
        ) as response:
            if not response.is_success:
                body = response.text
                raise WorkCoreApiError(
                    code="STREAM_FAILED",
                    message=body or "stream failed",
                    status_code=response.status_code,
                )
            for line in response.iter_lines():
                if not line:
                    continue
                if not line.startswith("data: "):
                    continue
                raw = line[len("data: ") :]
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    yield payload
