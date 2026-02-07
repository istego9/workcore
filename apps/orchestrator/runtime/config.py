from __future__ import annotations

import os
from dataclasses import dataclass

from .env import load_env


@dataclass
class StreamingConfig:
    backend: str
    kafka_bootstrap_servers: str
    kafka_topic: str
    kafka_group_id: str


@dataclass
class RuntimeConfig:
    streaming: StreamingConfig

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        load_env()
        backend = os.getenv("STREAMING_BACKEND", "memory")
        return cls(
            streaming=StreamingConfig(
                backend=backend,
                kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
                kafka_topic=os.getenv("KAFKA_TOPIC", "workflow-events"),
                kafka_group_id=os.getenv("KAFKA_GROUP_ID", "workflow-sse"),
            )
        )
