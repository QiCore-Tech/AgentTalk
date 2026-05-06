from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    OFFLINE = "offline"
    ONLINE = "online"
    ACTIVE = "active"
    WORKING = "working"
    STALE = "stale"


class ReceiveMode(StrEnum):
    AUTO_SUBMIT = "auto_submit"
    PASTE_ONLY = "paste_only"


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str = "ok"


class RelayRegisterRequest(BaseModel):
    machine_id: str = Field(min_length=1, max_length=120)
    host_name: str = Field(min_length=1, max_length=255)
    user_name: str = Field(min_length=1, max_length=120)


class RelayHeartbeatRequest(BaseModel):
    machine_id: str = Field(min_length=1, max_length=120)


class RelayResponse(BaseModel):
    machine_id: str
    host_name: str
    user_name: str
    last_seen_at: str


class AgentUpsertRequest(BaseModel):
    short_id: str = Field(min_length=1, max_length=120)
    machine_id: str = Field(min_length=1, max_length=120)
    owner: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=80)
    workspace: str = Field(default="", max_length=1000)
    tmux_target: str = Field(min_length=1, max_length=160)
    receive_mode: ReceiveMode = ReceiveMode.AUTO_SUBMIT
    status: AgentStatus = AgentStatus.ONLINE


class AgentResponse(BaseModel):
    short_id: str
    machine_id: str
    owner: str
    kind: str
    workspace: str
    tmux_target: str
    receive_mode: ReceiveMode
    status: AgentStatus
    updated_at: str
    relay_last_seen_at: str | None = None


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]
