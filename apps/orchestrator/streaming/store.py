from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Protocol

from .events import EventEnvelope


class EventStore(Protocol):
    def append(self, event: EventEnvelope) -> EventEnvelope:
        ...

    def list_events(self, run_id: str, after_id: Optional[str] = None) -> List[EventEnvelope]:
        ...

    def get_snapshot(self, run_id: str) -> Optional[EventEnvelope]:
        ...

    def set_snapshot(self, run_id: str, snapshot: EventEnvelope) -> None:
        ...

    def last_event(self, run_id: str) -> Optional[EventEnvelope]:
        ...

    def last_sequence(self, run_id: str) -> int:
        ...


@dataclass
class InMemoryEventStore:
    events: Dict[str, List[EventEnvelope]]
    snapshots: Dict[str, EventEnvelope]
    sequences: Dict[str, int]

    def __init__(self) -> None:
        self.events = {}
        self.snapshots = {}
        self.sequences = {}

    def append(self, event: EventEnvelope) -> EventEnvelope:
        next_seq = self.sequences.get(event.run_id, 0) + 1
        self.sequences[event.run_id] = next_seq
        event.sequence = next_seq
        self.events.setdefault(event.run_id, []).append(event)
        return event

    def list_events(self, run_id: str, after_id: Optional[str] = None) -> List[EventEnvelope]:
        items = list(self.events.get(run_id, []))
        if not after_id:
            return items
        for idx, event in enumerate(items):
            if event.id == after_id:
                return items[idx + 1 :]
        return items

    def get_snapshot(self, run_id: str) -> Optional[EventEnvelope]:
        return self.snapshots.get(run_id)

    def set_snapshot(self, run_id: str, snapshot: EventEnvelope) -> None:
        if snapshot.sequence <= 0:
            snapshot.sequence = self.sequences.get(run_id, 0)
        self.snapshots[run_id] = snapshot

    def last_event(self, run_id: str) -> Optional[EventEnvelope]:
        items = self.events.get(run_id, [])
        if not items:
            return None
        return items[-1]

    def last_sequence(self, run_id: str) -> int:
        return self.sequences.get(run_id, 0)
