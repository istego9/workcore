from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


EventEmitter = Callable[[str, Optional[Dict[str, Any]]], None]


@dataclass
class ExecutorResult:
    output: Any
    trace_id: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    raw_output: Optional[Any] = None
