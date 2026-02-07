from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.orchestrator.executors.types import EventEmitter, ExecutorResult


@dataclass
class MockAgentExecutor:
    """Lightweight executor for local/e2e tests without external calls."""

    emit_partial: bool = False

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
        return ExecutorResult(output=output, raw_output=output)
