from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


RunStatus = str
NodeStatus = str
InterruptStatus = str


@dataclass
class Edge:
    source: str
    target: str


@dataclass
class Node:
    id: str
    type: str
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Workflow:
    id: str
    version_id: str
    nodes: Dict[str, Node]
    edges: List[Edge]


@dataclass
class NodeRun:
    node_id: str
    status: NodeStatus
    attempt: int = 1
    output: Optional[Any] = None
    last_error: Optional[str] = None
    trace_id: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


@dataclass
class Interrupt:
    id: str
    run_id: str
    node_id: str
    type: str
    status: InterruptStatus
    prompt: str
    input_schema: Optional[Dict[str, Any]] = None
    allow_file_upload: bool = False
    input: Optional[Dict[str, Any]] = None
    files: Optional[List[Dict[str, Any]]] = None
    state_target: Optional[str] = None


@dataclass
class Run:
    id: str
    workflow_id: str
    version_id: str
    status: RunStatus
    inputs: Dict[str, Any]
    state: Dict[str, Any]
    mode: str = "live"
    outputs: Optional[Dict[str, Any]] = None
    node_runs: Dict[str, NodeRun] = field(default_factory=dict)
    node_outputs: Dict[str, Any] = field(default_factory=dict)
    interrupts: Dict[str, Interrupt] = field(default_factory=dict)
    branch_selection: Dict[str, str] = field(default_factory=dict)
    loop_state: Dict[str, int] = field(default_factory=dict)
    skipped_nodes: set = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Event:
    type: str
    run_id: str
    workflow_id: str
    version_id: str
    node_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
