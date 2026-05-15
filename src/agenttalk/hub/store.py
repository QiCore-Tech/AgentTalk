from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agenttalk.hub.models import (
    AgentAlert,
    AgentContextResponse,
    AgentHealthReport,
    AgentResponse,
    AgentStatus,
    AgentContextUpdateRequest,
    AgentUpsertRequest,
    MessageCreateRequest,
    MessageResponse,
    MessageResponseText,
    MessageResponseUpdateRequest,
    MessageStatus,
    RelayRegisterRequest,
    RelayResponse,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class AgentFilters:
    owner: str | None = None
    machine_id: str | None = None
    status: AgentStatus | None = None


class HubStore:
    def __init__(self, database_path: Path, *, heartbeat_ttl_seconds: int = 30) -> None:
        self.database_path = database_path
        self.heartbeat_ttl_seconds = heartbeat_ttl_seconds
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS relays (
                    machine_id TEXT PRIMARY KEY,
                    host_name TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    lan_ip TEXT DEFAULT '',
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agents (
                    short_id TEXT PRIMARY KEY,
                    machine_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    owner_open_id TEXT DEFAULT '',
                    kind TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    tmux_target TEXT NOT NULL,
                    receive_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    health_output_fingerprint TEXT DEFAULT '',
                    health_detected_errors TEXT DEFAULT '',
                    auto_resume_enabled INTEGER DEFAULT 1,
                    auto_resume_message TEXT DEFAULT '继续',
                    FOREIGN KEY(machine_id) REFERENCES relays(machine_id)
                );

                CREATE INDEX IF NOT EXISTS idx_agents_owner ON agents(owner);
                CREATE INDEX IF NOT EXISTS idx_agents_machine_id ON agents(machine_id);

                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    target TEXT NOT NULL,
                    target_machine_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    done_marker TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_target_machine_status
                    ON messages(target_machine_id, status, created_at);

                CREATE TABLE IF NOT EXISTS message_responses (
                    message_id TEXT PRIMARY KEY,
                    response_text TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(message_id) REFERENCES messages(message_id)
                );

                CREATE TABLE IF NOT EXISTS agent_contexts (
                    short_id TEXT PRIMARY KEY,
                    context TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(short_id) REFERENCES agents(short_id)
                );

                CREATE TABLE IF NOT EXISTS agent_alerts (
                    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    short_id TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    acknowledged INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_alerts_short_id ON agent_alerts(short_id);
                CREATE INDEX IF NOT EXISTS idx_alerts_created ON agent_alerts(created_at);

                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                -- User machines (development environments)
                CREATE TABLE IF NOT EXISTS machines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    host_name TEXT NOT NULL,
                    relay_machine_id TEXT UNIQUE NOT NULL,
                    status TEXT DEFAULT 'offline',
                    last_seen_at TEXT,
                    capabilities TEXT,
                    visibility TEXT DEFAULT 'private',
                    shared_with TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_machines_user ON machines(user_id);
                CREATE INDEX IF NOT EXISTS idx_machines_relay ON machines(relay_machine_id);

                -- Workspaces
                CREATE TABLE IF NOT EXISTS workspaces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    machine_id INTEGER NOT NULL,
                    description TEXT,
                    visibility TEXT DEFAULT 'private',
                    shared_with TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(machine_id) REFERENCES machines(id)
                );
                CREATE INDEX IF NOT EXISTS idx_workspaces_owner ON workspaces(owner_id);
                CREATE INDEX IF NOT EXISTS idx_workspaces_machine ON workspaces(machine_id);

                -- Tasks (orchestrator job tickets)
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT UNIQUE NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    owner_id TEXT NOT NULL,
                    target_workspace_id INTEGER,
                    target_machine_id INTEGER,
                    raw_request TEXT,
                    parsed_steps TEXT NOT NULL,
                    result TEXT,
                    logs TEXT,
                    created_agent_id TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    timeout_seconds INTEGER DEFAULT 3600,
                    error TEXT,
                    current_step INTEGER DEFAULT 0,
                    total_steps INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);

                -- Agent permissions
                CREATE TABLE IF NOT EXISTS agent_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_short_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    granted_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(agent_short_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_permissions_agent ON agent_permissions(agent_short_id);
                CREATE INDEX IF NOT EXISTS idx_permissions_user ON agent_permissions(user_id);

                -- Feishu bots (user-managed bots)
                CREATE TABLE IF NOT EXISTS feishu_bots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    app_id TEXT NOT NULL,
                    app_secret TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, app_id)
                );
                CREATE INDEX IF NOT EXISTS idx_feishu_bots_user ON feishu_bots(user_id);

                -- Agent notification routes
                CREATE TABLE IF NOT EXISTS agent_notification_routes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_short_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    destination_type TEXT NOT NULL,
                    destination_id TEXT NOT NULL,
                    feishu_bot_id INTEGER NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(feishu_bot_id) REFERENCES feishu_bots(id)
                );
                CREATE INDEX IF NOT EXISTS idx_routes_agent ON agent_notification_routes(agent_short_id);
                CREATE INDEX IF NOT EXISTS idx_routes_user ON agent_notification_routes(user_id);
                CREATE INDEX IF NOT EXISTS idx_routes_event ON agent_notification_routes(event_type);

                -- User Feishu bindings (for private chat)
                CREATE TABLE IF NOT EXISTS user_feishu_bindings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    open_id TEXT NOT NULL,
                    bot_id INTEGER NOT NULL,
                    bound_at TEXT NOT NULL,
                    UNIQUE(user_id, bot_id),
                    UNIQUE(open_id, bot_id),
                    FOREIGN KEY(bot_id) REFERENCES feishu_bots(id)
                );
                CREATE INDEX IF NOT EXISTS idx_bindings_user ON user_feishu_bindings(user_id);
                CREATE INDEX IF NOT EXISTS idx_bindings_openid ON user_feishu_bindings(open_id);

                -- Local users (for username/password auth)
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT UNIQUE NOT NULL,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT DEFAULT '',
                    email TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
                """
            )

            # Migrate existing databases
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Apply schema migrations for existing databases."""
        # Migrate: add auto_resume columns if missing
        try:
            conn.execute("SELECT auto_resume_enabled FROM agents LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE agents ADD COLUMN auto_resume_enabled INTEGER DEFAULT 1")
            conn.execute("ALTER TABLE agents ADD COLUMN auto_resume_message TEXT DEFAULT '继续'")

        # Migrate: add workspace_id and created_by to agents
        try:
            conn.execute("SELECT workspace_id FROM agents LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE agents ADD COLUMN workspace_id INTEGER")
        try:
            conn.execute("SELECT created_by FROM agents LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE agents ADD COLUMN created_by TEXT")

    def register_relay(self, request: RelayRegisterRequest) -> RelayResponse:
        now = format_time(utc_now())
        # Ensure lan_ip column exists for backward compatibility
        with self.connect() as conn:
            try:
                conn.execute("SELECT lan_ip FROM relays LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE relays ADD COLUMN lan_ip TEXT DEFAULT ''")
            conn.execute(
                """
                INSERT INTO relays (machine_id, host_name, user_name, lan_ip, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(machine_id) DO UPDATE SET
                    host_name = excluded.host_name,
                    user_name = excluded.user_name,
                    lan_ip = excluded.lan_ip,
                    last_seen_at = excluded.last_seen_at
                """,
                (request.machine_id, request.host_name, request.user_name, request.lan_ip or "", now),
            )
        return RelayResponse(
            machine_id=request.machine_id,
            host_name=request.host_name,
            user_name=request.user_name,
            lan_ip=request.lan_ip or "",
            last_seen_at=now,
        )

    def heartbeat(self, machine_id: str) -> RelayResponse | None:
        now = format_time(utc_now())
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT machine_id, host_name, user_name, lan_ip, last_seen_at FROM relays WHERE machine_id = ?",
                (machine_id,),
            ).fetchone()
            if existing is None:
                return None
            conn.execute("UPDATE relays SET last_seen_at = ? WHERE machine_id = ?", (now, machine_id))
        return RelayResponse(
            machine_id=str(existing["machine_id"]),
            host_name=str(existing["host_name"]),
            user_name=str(existing["user_name"]),
            lan_ip=str(existing["lan_ip"]) if existing["lan_ip"] else "",
            last_seen_at=now,
        )

    def relay_exists(self, machine_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM relays WHERE machine_id = ?", (machine_id,)).fetchone()
        return row is not None

    def get_relay(self, machine_id: str) -> dict[str, str] | None:
        """Get relay info by machine_id."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT machine_id, host_name, user_name, lan_ip, last_seen_at FROM relays WHERE machine_id = ?",
                (machine_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "machine_id": str(row["machine_id"]),
            "host_name": str(row["host_name"]),
            "user_name": str(row["user_name"]),
            "lan_ip": str(row["lan_ip"]) if row["lan_ip"] else "",
            "last_seen_at": str(row["last_seen_at"]),
        }

    def upsert_agent(self, request: AgentUpsertRequest) -> AgentResponse | None:
        if not self.relay_exists(request.machine_id):
            return None
        now = format_time(utc_now())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agents (
                    short_id, machine_id, owner, kind, workspace, tmux_target,
                    receive_mode, status, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(short_id) DO UPDATE SET
                    machine_id = excluded.machine_id,
                    owner = excluded.owner,
                    kind = excluded.kind,
                    workspace = excluded.workspace,
                    tmux_target = excluded.tmux_target,
                    receive_mode = excluded.receive_mode,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    request.short_id,
                    request.machine_id,
                    request.owner,
                    request.kind,
                    request.workspace,
                    request.tmux_target,
                    request.receive_mode.value,
                    request.status.value,
                    now,
                ),
            )
        return self.get_agent(request.short_id)

    def report_health(self, report: AgentHealthReport) -> AgentResponse | None:
        agent = self.get_agent(report.short_id)
        if agent is None:
            return None
        now = format_time(utc_now())
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE agents SET
                    status = ?,
                    updated_at = ?,
                    health_output_fingerprint = ?,
                    health_detected_errors = ?
                WHERE short_id = ?
                """,
                (
                    report.status.value,
                    now,
                    report.output_fingerprint,
                    ",".join(report.detected_errors),
                    report.short_id,
                ),
            )
        return self.get_agent(report.short_id)

    def list_agents(self, filters: AgentFilters | None = None) -> list[AgentResponse]:
        filters = filters or AgentFilters()
        clauses: list[str] = []
        values: list[Any] = []
        if filters.owner:
            clauses.append("a.owner = ?")
            values.append(filters.owner)
        if filters.machine_id:
            clauses.append("a.machine_id = ?")
            values.append(filters.machine_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    a.short_id,
                    a.machine_id,
                    a.owner,
                    a.kind,
                    a.workspace,
                    a.tmux_target,
                    a.receive_mode,
                    a.status,
                    a.updated_at,
                    a.health_output_fingerprint,
                    a.health_detected_errors,
                    a.auto_resume_enabled,
                    a.auto_resume_message,
                    r.last_seen_at AS relay_last_seen_at
                FROM agents a
                LEFT JOIN relays r ON r.machine_id = a.machine_id
                {where}
                ORDER BY a.short_id
                """,
                values,
            ).fetchall()
        agents = [self._agent_from_row(row) for row in rows]
        if filters.status:
            agents = [agent for agent in agents if agent.status == filters.status]
        return agents

    def get_agent(self, short_id: str) -> AgentResponse | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    a.short_id,
                    a.machine_id,
                    a.owner,
                    a.kind,
                    a.workspace,
                    a.tmux_target,
                    a.receive_mode,
                    a.status,
                    a.updated_at,
                    a.health_output_fingerprint,
                    a.health_detected_errors,
                    a.auto_resume_enabled,
                    a.auto_resume_message,
                    r.last_seen_at AS relay_last_seen_at
                FROM agents a
                LEFT JOIN relays r ON r.machine_id = a.machine_id
                WHERE a.short_id = ?
                """,
                (short_id,),
            ).fetchone()
        if row is None:
            return None
        return self._agent_from_row(row)

    def delete_agent(self, short_id: str) -> bool:
        with self.connect() as conn:
            conn.execute("DELETE FROM agent_contexts WHERE short_id = ?", (short_id,))
            conn.execute("DELETE FROM agent_alerts WHERE short_id = ?", (short_id,))
            cursor = conn.execute("DELETE FROM agents WHERE short_id = ?", (short_id,))
            return cursor.rowcount > 0

    def create_message(self, request: MessageCreateRequest) -> tuple[MessageResponse | None, str | None]:
        target = self.get_agent(request.to)
        if target is None:
            return None, "target_not_found"
        if target.status == AgentStatus.OFFLINE:
            return None, "target_offline"
        created_at = format_time(utc_now())
        message_id = self._next_message_id()
        done_marker = f"<<<AGENTTALK_DONE:{message_id}>>>"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    message_id, sender, target, target_machine_id, body, done_marker,
                    status, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    request.sender,
                    request.to,
                    target.machine_id,
                    request.body,
                    done_marker,
                    MessageStatus.SENT.value,
                    "",
                    created_at,
                    created_at,
                ),
            )
        return self.get_message(message_id), None

    def get_message(self, message_id: str) -> MessageResponse | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT message_id, sender, target, target_machine_id, body, done_marker,
                       status, error, created_at, updated_at
                FROM messages
                WHERE message_id = ?
                """,
                (message_id,),
            ).fetchone()
        if row is None:
            return None
        return self._message_from_row(row)

    def next_message_for_relay(self, machine_id: str) -> MessageResponse | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT message_id, sender, target, target_machine_id, body, done_marker,
                       status, error, created_at, updated_at
                FROM messages
                WHERE target_machine_id = ? AND status = ?
                ORDER BY created_at
                LIMIT 1
                """,
                (machine_id, MessageStatus.SENT.value),
            ).fetchone()
            if row is None:
                return None
            now = format_time(utc_now())
            conn.execute(
                "UPDATE messages SET status = ?, updated_at = ? WHERE message_id = ?",
                (MessageStatus.DELIVERED.value, now, row["message_id"]),
            )
        return self.get_message(str(row["message_id"]))

    def update_message_status(self, message_id: str, status: MessageStatus, error: str = "") -> MessageResponse | None:
        now = format_time(utc_now())
        with self.connect() as conn:
            existing = conn.execute("SELECT 1 FROM messages WHERE message_id = ?", (message_id,)).fetchone()
            if existing is None:
                return None
            conn.execute(
                "UPDATE messages SET status = ?, error = ?, updated_at = ? WHERE message_id = ?",
                (status.value, error, now, message_id),
            )
        return self.get_message(message_id)

    def update_message_response(
        self,
        message_id: str,
        request: MessageResponseUpdateRequest,
        *,
        max_chars: int = 20_000,
    ) -> MessageResponseText | None:
        if self.get_message(message_id) is None:
            return None
        now = format_time(utc_now())
        bounded = request.response_text[-max_chars:]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO message_responses (message_id, response_text, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    response_text = excluded.response_text,
                    updated_at = excluded.updated_at
                """,
                (message_id, bounded, now),
            )
        if request.completed:
            self.update_message_status(message_id, MessageStatus.COMPLETED)
        return MessageResponseText(message_id=message_id, response_text=bounded)

    def get_message_response(self, message_id: str) -> MessageResponseText | None:
        if self.get_message(message_id) is None:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT response_text FROM message_responses WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        return MessageResponseText(message_id=message_id, response_text=str(row["response_text"]) if row else "")

    def update_agent_context(
        self,
        short_id: str,
        request: AgentContextUpdateRequest,
        *,
        max_chars: int = 40_000,
    ) -> AgentContextResponse | None:
        if self.get_agent(short_id) is None:
            return None
        now = format_time(utc_now())
        bounded = request.context[-max_chars:]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_contexts (short_id, context, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(short_id) DO UPDATE SET
                    context = excluded.context,
                    updated_at = excluded.updated_at
                """,
                (short_id, bounded, now),
            )
        return AgentContextResponse(short_id=short_id, context=bounded, updated_at=now)

    def update_agent_status(self, short_id: str, status: AgentStatus) -> None:
        now = format_time(utc_now())
        with self.connect() as conn:
            conn.execute(
                "UPDATE agents SET status = ?, updated_at = ? WHERE short_id = ?",
                (status.value, now, short_id),
            )

    def get_agent_context(self, short_id: str) -> AgentContextResponse | None:
        if self.get_agent(short_id) is None:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT context, updated_at FROM agent_contexts WHERE short_id = ?",
                (short_id,),
            ).fetchone()
        if row is None:
            return AgentContextResponse(short_id=short_id, context="", updated_at=None)
        return AgentContextResponse(short_id=short_id, context=str(row["context"]), updated_at=str(row["updated_at"]))

    def create_alert(self, short_id: str, alert_type: str, message: str) -> AgentAlert:
        now = format_time(utc_now())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_alerts (short_id, alert_type, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (short_id, alert_type, message, now),
            )
        return AgentAlert(short_id=short_id, alert_type=alert_type, message=message, created_at=now)

    def list_alerts(self, short_id: str | None = None, unacknowledged_only: bool = False) -> list[AgentAlert]:
        clauses: list[str] = []
        values: list[Any] = []
        if short_id:
            clauses.append("short_id = ?")
            values.append(short_id)
        if unacknowledged_only:
            clauses.append("acknowledged = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT short_id, alert_type, message, created_at, acknowledged
                FROM agent_alerts
                {where}
                ORDER BY created_at DESC
                LIMIT 100
                """,
                values,
            ).fetchall()
        return [
            AgentAlert(
                short_id=str(row["short_id"]),
                alert_type=str(row["alert_type"]),
                message=str(row["message"]),
                created_at=str(row["created_at"]),
                acknowledged=bool(row["acknowledged"]),
            )
            for row in rows
        ]

    def acknowledge_alert(self, alert_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE agent_alerts SET acknowledged = 1 WHERE alert_id = ?",
                (alert_id,),
            )
            return cursor.rowcount > 0

    def set_owner_open_id(self, short_id: str, open_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE agents SET owner_open_id = ? WHERE short_id = ?",
                (open_id, short_id),
            )

    def get_owner_open_id(self, short_id: str) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT owner_open_id FROM agents WHERE short_id = ?",
                (short_id,),
            ).fetchone()
        return str(row["owner_open_id"]) if row else ""

    def get_agent_auto_resume(self, short_id: str) -> tuple[bool, str]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT auto_resume_enabled, auto_resume_message FROM agents WHERE short_id = ?",
                (short_id,),
            ).fetchone()
        if row is None:
            return True, "继续"
        enabled = bool(row["auto_resume_enabled"]) if row["auto_resume_enabled"] is not None else True
        message = str(row["auto_resume_message"]) if row["auto_resume_message"] is not None else "继续"
        return enabled, message

    def set_agent_auto_resume(self, short_id: str, enabled: bool, message: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE agents SET auto_resume_enabled = ?, auto_resume_message = ? WHERE short_id = ?",
                (1 if enabled else 0, message, short_id),
            )

    def _agent_from_row(self, row: sqlite3.Row) -> AgentResponse:
        stored_status = AgentStatus(str(row["status"]))
        relay_last_seen_at = row["relay_last_seen_at"]
        status = self._derive_status(stored_status=stored_status, relay_last_seen_at=relay_last_seen_at)
        errors_str = str(row["health_detected_errors"] or "")
        return AgentResponse(
            short_id=str(row["short_id"]),
            machine_id=str(row["machine_id"]),
            owner=str(row["owner"]),
            kind=str(row["kind"]),
            workspace=str(row["workspace"]),
            tmux_target=str(row["tmux_target"]),
            receive_mode=str(row["receive_mode"]),
            status=status,
            updated_at=str(row["updated_at"]),
            relay_last_seen_at=str(relay_last_seen_at) if relay_last_seen_at is not None else None,
            health_output_fingerprint=str(row["health_output_fingerprint"] or ""),
            health_detected_errors=errors_str.split(",") if errors_str else [],
            auto_resume_enabled=bool(row["auto_resume_enabled"]) if row["auto_resume_enabled"] is not None else True,
            auto_resume_message=str(row["auto_resume_message"] or "继续"),
        )

    def _derive_status(self, *, stored_status: AgentStatus, relay_last_seen_at: str | None) -> AgentStatus:
        if relay_last_seen_at is None:
            return AgentStatus.OFFLINE
        last_seen = parse_time(relay_last_seen_at)
        if utc_now() - last_seen > timedelta(seconds=self.heartbeat_ttl_seconds):
            return AgentStatus.OFFLINE
        return stored_status

    def _next_message_id(self) -> str:
        stamp = utc_now().strftime("%Y%m%d%H%M%S%f")
        return f"msg-{stamp}"

    def _message_from_row(self, row: sqlite3.Row) -> MessageResponse:
        return MessageResponse(
            message_id=str(row["message_id"]),
            sender=str(row["sender"]),
            target=str(row["target"]),
            target_machine_id=str(row["target_machine_id"]),
            body=str(row["body"]),
            done_marker=str(row["done_marker"]),
            status=MessageStatus(str(row["status"])),
            error=str(row["error"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def get_config(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row else None

    def set_config(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ==================== Machine Management ====================

    def create_machine(
        self,
        *,
        user_id: str,
        name: str,
        host_name: str,
        relay_machine_id: str,
        capabilities: list[str] | None = None,
    ) -> dict:
        """Register a new machine for a user."""
        now = format_time(utc_now())
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO machines (user_id, name, host_name, relay_machine_id, status, capabilities, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    name,
                    host_name,
                    relay_machine_id,
                    "online",
                    json.dumps(capabilities or []),
                    now,
                ),
            )
        return {
            "id": cursor.lastrowid,
            "user_id": user_id,
            "name": name,
            "host_name": host_name,
            "relay_machine_id": relay_machine_id,
            "status": "online",
            "created_at": now,
        }

    def get_machine(self, machine_id: int) -> dict | None:
        """Get machine by ID."""
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM machines WHERE id = ?", (machine_id,)).fetchone()
        if row is None:
            return None
        return self._machine_from_row(row)

    def get_machine_by_relay(self, relay_machine_id: str) -> dict | None:
        """Get machine by relay_machine_id."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM machines WHERE relay_machine_id = ?", (relay_machine_id,)
            ).fetchone()
        if row is None:
            return None
        return self._machine_from_row(row)

    def list_machines(self, user_id: str | None = None) -> list[dict]:
        """List machines. If user_id provided, filter by owner."""
        with self.connect() as conn:
            if user_id:
                rows = conn.execute(
                    "SELECT * FROM machines WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM machines ORDER BY created_at DESC").fetchall()
        return [self._machine_from_row(row) for row in rows]

    def update_machine_status(self, machine_id: int, status: str, last_seen_at: str | None = None) -> None:
        """Update machine status and last seen time."""
        now = last_seen_at or format_time(utc_now())
        with self.connect() as conn:
            conn.execute(
                "UPDATE machines SET status = ?, last_seen_at = ? WHERE id = ?",
                (status, now, machine_id),
            )

    def delete_machine(self, machine_id: int) -> bool:
        """Delete a machine and its associated workspaces."""
        with self.connect() as conn:
            # Delete associated workspaces first
            conn.execute("DELETE FROM workspaces WHERE machine_id = ?", (machine_id,))
            # Delete machine
            cursor = conn.execute("DELETE FROM machines WHERE id = ?", (machine_id,))
        return cursor.rowcount > 0

    def _machine_from_row(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a machine dict."""
        return {
            "id": row["id"],
            "user_id": str(row["user_id"]),
            "name": str(row["name"]),
            "host_name": str(row["host_name"]),
            "relay_machine_id": str(row["relay_machine_id"]),
            "status": str(row["status"]),
            "last_seen_at": str(row["last_seen_at"]) if row["last_seen_at"] else None,
            "capabilities": json.loads(str(row["capabilities"])) if row["capabilities"] else [],
            "visibility": str(row["visibility"]),
            "shared_with": json.loads(str(row["shared_with"])) if row["shared_with"] else [],
            "created_at": str(row["created_at"]),
        }

    # ==================== Workspace Management ====================

    def create_workspace(
        self,
        *,
        name: str,
        path: str,
        owner_id: str,
        machine_id: int,
        description: str = "",
    ) -> dict:
        """Create a new workspace."""
        now = format_time(utc_now())
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO workspaces (name, path, owner_id, machine_id, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, path, owner_id, machine_id, description, now),
            )
        return {
            "id": cursor.lastrowid,
            "name": name,
            "path": path,
            "owner_id": owner_id,
            "machine_id": machine_id,
            "description": description,
            "created_at": now,
        }

    def get_workspace(self, workspace_id: int) -> dict | None:
        """Get workspace by ID."""
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if row is None:
            return None
        return self._workspace_from_row(row)

    def list_workspaces(self, user_id: str | None = None, machine_id: int | None = None) -> list[dict]:
        """List workspaces with optional filters."""
        with self.connect() as conn:
            if user_id and machine_id:
                rows = conn.execute(
                    "SELECT * FROM workspaces WHERE owner_id = ? AND machine_id = ? ORDER BY created_at DESC",
                    (user_id, machine_id),
                ).fetchall()
            elif user_id:
                rows = conn.execute(
                    "SELECT * FROM workspaces WHERE owner_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
            elif machine_id:
                rows = conn.execute(
                    "SELECT * FROM workspaces WHERE machine_id = ? ORDER BY created_at DESC",
                    (machine_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM workspaces ORDER BY created_at DESC").fetchall()
        return [self._workspace_from_row(row) for row in rows]

    def delete_workspace(self, workspace_id: int) -> bool:
        """Delete a workspace."""
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        return cursor.rowcount > 0

    def _workspace_from_row(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a workspace dict."""
        return {
            "id": row["id"],
            "name": str(row["name"]),
            "path": str(row["path"]),
            "owner_id": str(row["owner_id"]),
            "machine_id": row["machine_id"],
            "description": str(row["description"]) if row["description"] else "",
            "visibility": str(row["visibility"]),
            "shared_with": json.loads(str(row["shared_with"])) if row["shared_with"] else [],
            "created_at": str(row["created_at"]),
        }

    # ==================== Task Management ====================

    def create_task(
        self,
        *,
        task_id: str,
        owner_id: str,
        task_type: str,
        target_machine_id: int | None = None,
        target_workspace_id: int | None = None,
        raw_request: str = "",
        parsed_steps: str = "",
        timeout_seconds: int = 3600,
    ) -> dict:
        """Create a new task."""
        now = format_time(utc_now())
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks (
                    task_id, type, status, owner_id, target_machine_id, target_workspace_id,
                    raw_request, parsed_steps, timeout_seconds, created_at, total_steps
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    task_type,
                    "pending",
                    owner_id,
                    target_machine_id,
                    target_workspace_id,
                    raw_request,
                    parsed_steps,
                    timeout_seconds,
                    now,
                    len(json.loads(parsed_steps)) if parsed_steps and parsed_steps.strip() else 0,
                ),
            )
        return {
            "id": cursor.lastrowid,
            "task_id": task_id,
            "type": task_type,
            "status": "pending",
            "owner_id": owner_id,
            "target_machine_id": target_machine_id,
            "target_workspace_id": target_workspace_id,
            "raw_request": raw_request,
            "parsed_steps": parsed_steps,
            "created_at": now,
        }

    def get_task(self, task_id: str) -> dict | None:
        """Get task by task_id."""
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._task_from_row(row)

    def update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        error: str = "",
        current_step: int | None = None,
        result: str = "",
    ) -> None:
        """Update task status and optional fields."""
        now = format_time(utc_now())
        with self.connect() as conn:
            updates = ["status = ?"]
            params: list[Any] = [status]

            if error:
                updates.append("error = ?")
                params.append(error)
            if current_step is not None:
                updates.append("current_step = ?")
                params.append(current_step)
            if result:
                updates.append("result = ?")
                params.append(result)

            if status == "running":
                updates.append("started_at = ?")
                params.append(now)
            elif status in ("completed", "failed", "cancelled"):
                updates.append("completed_at = ?")
                params.append(now)

            params.append(task_id)

            conn.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?",
                params,
            )

    def append_task_log(self, task_id: str, log_line: str) -> None:
        """Append a line to task logs."""
        now = format_time(utc_now())
        with self.connect() as conn:
            row = conn.execute("SELECT logs FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            current_logs = str(row["logs"]) if row and row["logs"] else ""
            new_logs = current_logs + f"\n[{now}] {log_line}" if current_logs else f"[{now}] {log_line}"
            conn.execute(
                "UPDATE tasks SET logs = ? WHERE task_id = ?",
                (new_logs, task_id),
            )

    def list_tasks(
        self,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List tasks with optional filters."""
        with self.connect() as conn:
            query = "SELECT * FROM tasks"
            params: list[Any] = []
            conditions = []

            if user_id:
                conditions.append("owner_id = ?")
                params.append(user_id)
            if status:
                conditions.append("status = ?")
                params.append(status)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
        return [self._task_from_row(row) for row in rows]

    def _task_from_row(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a task dict."""
        return {
            "id": row["id"],
            "task_id": str(row["task_id"]),
            "type": str(row["type"]),
            "status": str(row["status"]),
            "owner_id": str(row["owner_id"]),
            "target_workspace_id": row["target_workspace_id"],
            "target_machine_id": row["target_machine_id"],
            "raw_request": str(row["raw_request"]) if row["raw_request"] else "",
            "parsed_steps": str(row["parsed_steps"]) if row["parsed_steps"] else "",
            "result": str(row["result"]) if row["result"] else "",
            "logs": str(row["logs"]) if row["logs"] else "",
            "created_agent_id": str(row["created_agent_id"]) if row["created_agent_id"] else None,
            "created_at": str(row["created_at"]),
            "started_at": str(row["started_at"]) if row["started_at"] else None,
            "completed_at": str(row["completed_at"]) if row["completed_at"] else None,
            "timeout_seconds": row["timeout_seconds"],
            "error": str(row["error"]) if row["error"] else "",
            "current_step": row["current_step"],
            "total_steps": row["total_steps"],
        }

    # ==================== Permission Management ====================

    def grant_permission(
        self,
        agent_short_id: str,
        user_id: str,
        permission: str,
        granted_by: str,
    ) -> bool:
        """Grant permission to a user for an agent."""
        now = format_time(utc_now())
        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO agent_permissions (agent_short_id, user_id, permission, granted_by, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(agent_short_id, user_id) DO UPDATE SET
                        permission = excluded.permission,
                        granted_by = excluded.granted_by,
                        created_at = excluded.created_at
                    """,
                    (agent_short_id, user_id, permission, granted_by, now),
                )
                return True
            except sqlite3.Error:
                return False

    def revoke_permission(self, agent_short_id: str, user_id: str) -> bool:
        """Revoke permission from a user for an agent."""
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM agent_permissions WHERE agent_short_id = ? AND user_id = ?",
                (agent_short_id, user_id),
            )
        return cursor.rowcount > 0

    def check_permission(self, agent_short_id: str, user_id: str) -> str | None:
        """Check user's permission for an agent. Returns permission level or None."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT permission FROM agent_permissions WHERE agent_short_id = ? AND user_id = ?",
                (agent_short_id, user_id),
            ).fetchone()
        return str(row["permission"]) if row else None

    def list_permissions(self, agent_short_id: str) -> list[dict]:
        """List all permissions for an agent."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_permissions WHERE agent_short_id = ?",
                (agent_short_id,),
            ).fetchall()
        return [
            {
                "user_id": str(row["user_id"]),
                "permission": str(row["permission"]),
                "granted_by": str(row["granted_by"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    # ==================== Feishu Bot Management ====================

    def create_feishu_bot(self, user_id: str, name: str, app_id: str, app_secret: str) -> int:
        """Register a new Feishu bot. Returns bot_id."""
        now = format_time(utc_now())
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO feishu_bots (user_id, name, app_id, app_secret, status, created_at)
                VALUES (?, ?, ?, ?, 'active', ?)
                ON CONFLICT(user_id, app_id) DO UPDATE SET
                    name = excluded.name,
                    app_secret = excluded.app_secret,
                    status = 'active'
                """,
                (user_id, name, app_id, app_secret, now),
            )
            return cursor.lastrowid or 0

    def get_feishu_bot(self, bot_id: int) -> dict | None:
        """Get a Feishu bot by ID."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM feishu_bots WHERE id = ?",
                (bot_id,),
            ).fetchone()
        return self._feishu_bot_from_row(row) if row else None

    def list_feishu_bots(self, user_id: str | None = None) -> list[dict]:
        """List Feishu bots, optionally filtered by user."""
        with self.connect() as conn:
            if user_id:
                rows = conn.execute(
                    "SELECT * FROM feishu_bots WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM feishu_bots ORDER BY created_at DESC").fetchall()
        return [self._feishu_bot_from_row(row) for row in rows]

    def delete_feishu_bot(self, bot_id: int) -> bool:
        """Delete a Feishu bot."""
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM feishu_bots WHERE id = ?", (bot_id,))
        return cursor.rowcount > 0

    def _feishu_bot_from_row(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a Feishu bot dict."""
        return {
            "id": row["id"],
            "user_id": str(row["user_id"]),
            "name": str(row["name"]),
            "app_id": str(row["app_id"]),
            "app_secret": str(row["app_secret"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
        }

    # ==================== Notification Routes ====================

    def create_notification_route(
        self,
        agent_short_id: str,
        user_id: str,
        event_type: str,
        destination_type: str,
        destination_id: str,
        feishu_bot_id: int,
    ) -> int:
        """Create a notification route. Returns route_id."""
        now = format_time(utc_now())
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_notification_routes
                (agent_short_id, user_id, event_type, destination_type, destination_id, feishu_bot_id, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (agent_short_id, user_id, event_type, destination_type, destination_id, feishu_bot_id, now),
            )
            return cursor.lastrowid or 0

    def get_notification_route(self, route_id: int) -> dict | None:
        """Get a notification route by ID."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_notification_routes WHERE id = ?",
                (route_id,),
            ).fetchone()
        return self._route_from_row(row) if row else None

    def list_notification_routes(
        self,
        agent_short_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
    ) -> list[dict]:
        """List notification routes with optional filters."""
        with self.connect() as conn:
            query = "SELECT * FROM agent_notification_routes WHERE enabled = 1"
            params: list[Any] = []

            if agent_short_id:
                query += " AND agent_short_id = ?"
                params.append(agent_short_id)
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)

            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
        return [self._route_from_row(row) for row in rows]

    def update_notification_route(self, route_id: int, enabled: bool | None = None) -> bool:
        """Update a notification route."""
        with self.connect() as conn:
            if enabled is not None:
                cursor = conn.execute(
                    "UPDATE agent_notification_routes SET enabled = ? WHERE id = ?",
                    (1 if enabled else 0, route_id),
                )
                return cursor.rowcount > 0
        return False

    def delete_notification_route(self, route_id: int) -> bool:
        """Delete a notification route."""
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM agent_notification_routes WHERE id = ?", (route_id,))
        return cursor.rowcount > 0

    def _route_from_row(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a route dict."""
        return {
            "id": row["id"],
            "agent_short_id": str(row["agent_short_id"]),
            "user_id": str(row["user_id"]),
            "event_type": str(row["event_type"]),
            "destination_type": str(row["destination_type"]),
            "destination_id": str(row["destination_id"]),
            "feishu_bot_id": row["feishu_bot_id"],
            "enabled": bool(row["enabled"]),
            "created_at": str(row["created_at"]),
        }

    # ==================== User Feishu Bindings ====================

    def bind_user_feishu(self, user_id: str, open_id: str, bot_id: int) -> bool:
        """Bind a user's Feishu open_id to their Hub account."""
        now = format_time(utc_now())
        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO user_feishu_bindings (user_id, open_id, bot_id, bound_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, bot_id) DO UPDATE SET
                        open_id = excluded.open_id,
                        bound_at = excluded.bound_at
                    """,
                    (user_id, open_id, bot_id, now),
                )
                return True
            except sqlite3.Error:
                return False

    def find_user_by_open_id(self, open_id: str, bot_id: int) -> str | None:
        """Find Hub user_id by Feishu open_id and bot_id."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM user_feishu_bindings WHERE open_id = ? AND bot_id = ?",
                (open_id, bot_id),
            ).fetchone()
        return str(row["user_id"]) if row else None

    def find_binding_by_user(self, user_id: str, bot_id: int) -> dict | None:
        """Find binding by user_id and bot_id."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_feishu_bindings WHERE user_id = ? AND bot_id = ?",
                (user_id, bot_id),
            ).fetchone()
        if not row:
            return None
        return {
            "user_id": str(row["user_id"]),
            "open_id": str(row["open_id"]),
            "bot_id": row["bot_id"],
            "bound_at": str(row["bound_at"]),
        }

    # ==================== Local User Management ====================

    def create_user(self, user_id: str, username: str, password_hash: str, display_name: str = "", email: str = "") -> dict:
        """Register a new local user."""
        now = format_time(utc_now())
        with self.connect() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO users (user_id, username, password_hash, display_name, email, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, username, password_hash, display_name, email, now),
                )
                return {
                    "id": cursor.lastrowid,
                    "user_id": user_id,
                    "username": username,
                    "display_name": display_name,
                    "email": email,
                    "created_at": now,
                }
            except sqlite3.IntegrityError:
                raise ValueError(f"User already exists: {username}")

    def get_user_by_username(self, username: str) -> dict | None:
        """Get user by username."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "user_id": str(row["user_id"]),
            "username": str(row["username"]),
            "password_hash": str(row["password_hash"]),
            "display_name": str(row["display_name"]),
            "email": str(row["email"]),
            "created_at": str(row["created_at"]),
        }

    def get_user_by_id(self, user_id: str) -> dict | None:
        """Get user by user_id."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "user_id": str(row["user_id"]),
            "username": str(row["username"]),
            "display_name": str(row["display_name"]),
            "email": str(row["email"]),
            "created_at": str(row["created_at"]),
        }
