from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


_DEF_PATH = Path(".env")


def load_env(path: Optional[str] = None) -> None:
    env_path = Path(path) if path else _DEF_PATH
    if env_path.exists():
        load_dotenv(env_path)


def get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(name, default)
