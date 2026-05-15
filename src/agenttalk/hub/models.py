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
    SUBMITTED = "submitted"
    ACKED = "acked"
    SUBMIT_UNCONFIRMED = "submit_unconfirmed"
    # Text was pasted into the target pane but Enter was NOT submitted because
    # the binding is in paste_only receive mode. The peer has the message in
    # their input box but has not seen it yet — caller must verify out-of-band
    # before treating the send as "delivered to the agent".
    INJECTED_PASTE_ONLY = "injected_paste_only"
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
    lan_ip: str = Field(default="", max_length=255)


class RelayHeartbeatRequest(BaseModel):
    machine_id: str = Field(min_length=1, max_length=120)


class RelayResponse(BaseModel):
    machine_id: str
    host_name: str
    user_name: str
    lan_ip: str = ""
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


# ==================== Machine / Workspace / Task Models ====================

class Visibility(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"
    PUBLIC = "public"


class Permission(StrEnum):
    VIEW = "view"
    MANAGE = "manage"
    ADMIN = "admin"


class MachineCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    host_name: str = Field(min_length=1, max_length=255)
    capabilities: list[str] = Field(default_factory=list)


class MachineResponse(BaseModel):
    id: int
    user_id: str
    name: str
    host_name: str
    relay_machine_id: str
    status: str
    last_seen_at: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    visibility: str = "private"
    shared_with: list[str] = Field(default_factory=list)
    created_at: str


class MachineListResponse(BaseModel):
    machines: list[MachineResponse]


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=1000)
    machine_id: int = Field(ge=1)
    description: str = Field(default="", max_length=500)


class WorkspaceResponse(BaseModel):
    id: int
    name: str
    path: str
    owner_id: str
    machine_id: int
    description: str = ""
    visibility: str = "private"
    shared_with: list[str] = Field(default_factory=list)
    created_at: str


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceResponse]


class TaskCreateRequest(BaseModel):
    raw_request: str = Field(min_length=1)
    target_machine_id: int = Field(ge=1)
    target_workspace_id: int | None = None


class TaskResponse(BaseModel):
    id: int
    task_id: str
    type: str
    status: str
    owner_id: str
    target_workspace_id: int | None = None
    target_machine_id: int | None = None
    raw_request: str
    result: str = ""
    logs: str = ""
    created_agent_id: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str = ""
    current_step: int = 0
    total_steps: int = 0


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]


class PermissionGrantRequest(BaseModel):
    user_id: str = Field(min_length=1)
    permission: Permission = Permission.VIEW


# ==================== Feishu Bot / Notification Models ====================

class FeishuBotCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    app_id: str = Field(min_length=1, max_length=120)
    app_secret: str = Field(min_length=1, max_length=255)


class FeishuBotResponse(BaseModel):
    id: int
    user_id: str
    name: str
    app_id: str
    app_secret: str = "***"
    status: str
    created_at: str


class FeishuBotListResponse(BaseModel):
    bots: list[FeishuBotResponse]


class NotificationRouteCreateRequest(BaseModel):
    agent_short_id: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=80)
    destination_type: str = Field(min_length=1, max_length=20)
    destination_id: str = Field(min_length=1, max_length=255)
    feishu_bot_id: int = Field(ge=1)


class NotificationRouteResponse(BaseModel):
    id: int
    agent_short_id: str
    user_id: str
    event_type: str
    destination_type: str
    destination_id: str
    feishu_bot_id: int
    enabled: bool
    created_at: str


class NotificationRouteListResponse(BaseModel):
    routes: list[NotificationRouteResponse]


class FeishuBindRequest(BaseModel):
    open_id: str = Field(min_length=1)
    bot_id: int = Field(ge=1)
    token: str = Field(min_length=1)
