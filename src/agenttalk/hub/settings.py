from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HubSettings:
    database_path: Path
    token: str
    heartbeat_ttl_seconds: int = 30


def default_database_path() -> Path:
    return Path.home() / ".agenttalk" / "hub.sqlite3"
