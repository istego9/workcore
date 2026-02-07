from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import httpx

from .signing import HEADER_SIGNATURE, HEADER_TIMESTAMP, sign_payload


SendFunc = Callable[[str, Dict[str, Any], Dict[str, str], float], int]


@dataclass
class DispatcherConfig:
    timeout_s: float = 5.0
    max_attempts: int = 5
    base_backoff_s: float = 2.0


class OutboundDispatcher:
    def __init__(self, config: Optional[DispatcherConfig] = None, sender: Optional[SendFunc] = None) -> None:
        self.config = config or DispatcherConfig()
        self._sender = sender or self._default_sender

    async def send(self, url: str, payload: Dict[str, Any], secret: str) -> int:
        timestamp = str(int(time.time()))
        signature = sign_payload(secret, timestamp, json_bytes(payload))
        headers = {
            "Content-Type": "application/json",
            HEADER_TIMESTAMP: timestamp,
            HEADER_SIGNATURE: signature,
        }
        return await self._sender(url, payload, headers, self.config.timeout_s)

    async def _default_sender(self, url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout_s: float) -> int:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(url, json=payload, headers=headers)
        return response.status_code


def json_bytes(payload: Dict[str, Any]) -> bytes:
    import json

    return json.dumps(payload).encode("utf-8")
