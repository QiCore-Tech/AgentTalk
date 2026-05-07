from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    OFFLINE = "offline"
    IDLE = "idle"
    WORKING = "working"
    CRASHED = "crashed"
    ERROR = "error"
    STALE = "stale"


class ReceiveMode(StrEnum):
    AUTO_SUBMIT = "auto_submit"
    PASTE_ONLY = "paste_only"


class MessageStatus(StrEnum):
    SENT = "sent"
    DELIVERED = "delivered"
    INJECTED = "injected"
    WORKING = "working"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    FAILED = "failed"


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
    status: AgentStatus = AgentStatus.IDLE


class AgentHealthReport(BaseModel):
    short_id: str = Field(min_length=1, max_length=120)
    pane_alive: bool = True
    process_alive: bool = True
    recent_output: str = Field(default="", max_length=2000)
    output_fingerprint: str = Field(default="", max_length=64)
    detected_errors: list[str] = Field(default_factory=list)
    detected_pauses: list[str] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE


class AgentAlert(BaseModel):
    short_id: str
    alert_type: str
    message: str
    created_at: str
    acknowledged: bool = False


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
    health_output_fingerprint: str | None = None
    health_detected_errors: list[str] = Field(default_factory=list)
    auto_resume_enabled: bool = True
    auto_resume_message: str = "继续"


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]


class MessageCreateRequest(BaseModel):
    to: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1)
    sender: str = Field(default="web", min_length=1, max_length=120)


class MessageStatusUpdateRequest(BaseModel):
    status: MessageStatus
    error: str = ""


class MessageResponse(BaseModel):
    message_id: str
    sender: str
    target: str
    target_machine_id: str
    body: str
    done_marker: str
    status: MessageStatus
    error: str = ""
    created_at: str
    updated_at: str


class PendingMessageResponse(BaseModel):
    message: MessageResponse | None


class MessageResponseUpdateRequest(BaseModel):
    response_text: str = ""
    completed: bool = False


class MessageResponseText(BaseModel):
    message_id: str
    response_text: str


class AgentContextUpdateRequest(BaseModel):
    context: str = ""


class AgentContextResponse(BaseModel):
    short_id: str
    context: str
    updated_at: str | None = None
