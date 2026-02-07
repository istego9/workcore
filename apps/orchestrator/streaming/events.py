from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class EventEnvelope:
    id: str
    type: str
    run_id: str
    workflow_id: str
    version_id: str
    node_id: Optional[str]
    payload: Dict[str, Any]
    timestamp: float
    sequence: int = 0
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    import_run_id: Optional[str] = None

    def to_sse(self) -> Dict[str, str]:
        data = {
            "event_id": self.id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "version_id": self.version_id,
            "node_id": self.node_id,
            "type": self.type,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "import_run_id": self.import_run_id,
        }
        return {
            "event": self.type,
            "id": self.id,
            "data": json.dumps(data),
        }


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


def now_ts() -> float:
    return time.time()
