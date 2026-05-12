from __future__ import annotations

import json
import os
import socket
from dataclasses import field
from pathlib import Path

from pydantic import BaseModel, Field

from agenttalk.hub.models import ReceiveMode


def default_config_path() -> Path:
    return Path.home() / ".agenttalk" / "config.json"


def default_machine_id() -> str:
    return f"{socket.gethostname()}:{os.environ.get('USER', 'unknown')}"


def default_lan_ip() -> str:
    """Detect the primary LAN IP address."""
    configured = os.environ.get("AGENTTALK_LAN_IP", "").strip()
    if configured:
        return configured
    try:
        # Try to get the IP used for default route
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        # Connect to a public DNS server to determine outgoing interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            # Fallback: hostname -I
            import subprocess
            result = subprocess.run(
                ["hostname", "-I"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip().split()[0]
        except Exception:
            pass
        return ""


class AgentBinding(BaseModel):
    short_id: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    workspace: str = ""
    tmux_target: str = Field(min_length=1)
    pane_id: str = ""
    receive_mode: ReceiveMode = ReceiveMode.AUTO_SUBMIT


class LLMConfig(BaseModel):
    """LLM configuration for agent status analysis"""
    base_url: str = ""  # e.g., "http://192.168.31.100:9000/v1" or "https://api.openai.com/v1"
    api_key: str = ""   # API key (can be empty for local LLMs)
    model: str = "gpt-4o-mini"  # Model name
    enabled: bool = False  # Whether to use LLM for status analysis


class AgentTalkConfig(BaseModel):
    hub_url: str = "http://127.0.0.1:8787"
    token: str = ""
    machine_id: str = Field(default_factory=default_machine_id)
    host_name: str = Field(default_factory=socket.gethostname)
    user_name: str = Field(default_factory=lambda: os.environ.get("USER", "unknown"))
    lan_ip: str = Field(default_factory=default_lan_ip)
    agents: list[AgentBinding] = field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)


def load_config(path: Path | None = None) -> AgentTalkConfig:
    config_path = path or default_config_path()
    if not config_path.exists():
        return AgentTalkConfig()
    return AgentTalkConfig.model_validate_json(config_path.read_text(encoding="utf-8"))


def save_config(config: AgentTalkConfig, path: Path | None = None) -> None:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def upsert_binding(config: AgentTalkConfig, binding: AgentBinding) -> AgentTalkConfig:
    agents = [agent for agent in config.agents if agent.short_id != binding.short_id]
    agents.append(binding)
    agents.sort(key=lambda agent: agent.short_id)
    return config.model_copy(update={"agents": agents})


def remove_binding(config: AgentTalkConfig, short_id: str) -> AgentTalkConfig:
    return config.model_copy(update={"agents": [agent for agent in config.agents if agent.short_id != short_id]})
