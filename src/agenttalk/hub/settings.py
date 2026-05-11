from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HubSettings:
    database_path: Path
    token: str
    heartbeat_ttl_seconds: int = 30
    web_dist_path: Path | None = None
    public_base_url: str = ""
    feishu_enable: bool = False
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_alert_chat_id: str = ""
    # Authentication
    auth_mode: str = "token"  # "token" | "local" | "casdoor" | "both"
    # Casdoor OAuth settings
    casdoor_endpoint: str = ""  # e.g., "https://auth.qicore.tech"
    casdoor_client_id: str = ""
    casdoor_client_secret: str = ""
    casdoor_app_name: str = ""
    casdoor_org_name: str = ""
    # Local auth settings
    local_auth_enabled: bool = False
    jwt_secret: str = ""
    jwt_expiry_hours: int = 24


def default_database_path() -> Path:
    return Path.home() / ".agenttalk" / "hub.sqlite3"
