from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from apps.orchestrator.executors.types import EventEmitter, ExecutorResult


@dataclass
class MockAgentExecutor:
    """Lightweight executor for local/e2e tests without external calls."""

    emit_partial: bool = False

    @staticmethod
    def _to_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(value)

    @classmethod
    def _estimate_tokens(cls, value: Any) -> int:
        text = cls._to_text(value)
        if not text:
            return 0
        # Rough approximation used only in mock mode; no provider billing call is made.
        return max(1, math.ceil(len(text) / 4))

    def __call__(self, run, node, emit: EventEmitter) -> ExecutorResult:
        instructions = node.config.get("instructions", "")
        user_input = node.config.get("user_input", "") or ""
        if self.emit_partial and user_input:
            emit("message_generated", {"text": str(user_input)})
        output: Any = {
            "mock": True,
            "resolved_instructions": instructions,
            "resolved_input": user_input,
        }
        input_tokens = self._estimate_tokens(instructions) + self._estimate_tokens(user_input)
        output_tokens = self._estimate_tokens(output)
        usage = {
            "provider": "mock",
            "estimated": True,
            "requests": 0,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
        return ExecutorResult(output=output, raw_output=output, usage=usage)
