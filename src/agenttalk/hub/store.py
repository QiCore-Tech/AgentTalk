from __future__ import annotations

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
                """
            )
            # Migrate existing databases: add auto_resume columns if missing
            try:
                conn.execute("SELECT auto_resume_enabled FROM agents LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE agents ADD COLUMN auto_resume_enabled INTEGER DEFAULT 1")
                conn.execute("ALTER TABLE agents ADD COLUMN auto_resume_message TEXT DEFAULT '继续'")

    def register_relay(self, request: RelayRegisterRequest) -> RelayResponse:
        now = format_time(utc_now())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO relays (machine_id, host_name, user_name, last_seen_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(machine_id) DO UPDATE SET
                    host_name = excluded.host_name,
                    user_name = excluded.user_name,
                    last_seen_at = excluded.last_seen_at
                """,
                (request.machine_id, request.host_name, request.user_name, now),
            )
        return RelayResponse(
            machine_id=request.machine_id,
            host_name=request.host_name,
            user_name=request.user_name,
            last_seen_at=now,
        )

    def heartbeat(self, machine_id: str) -> RelayResponse | None:
        now = format_time(utc_now())
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT machine_id, host_name, user_name, last_seen_at FROM relays WHERE machine_id = ?",
                (machine_id,),
            ).fetchone()
            if existing is None:
                return None
            conn.execute("UPDATE relays SET last_seen_at = ? WHERE machine_id = ?", (now, machine_id))
        return RelayResponse(
            machine_id=str(existing["machine_id"]),
            host_name=str(existing["host_name"]),
            user_name=str(existing["user_name"]),
            last_seen_at=now,
        )

    def relay_exists(self, machine_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM relays WHERE machine_id = ?", (machine_id,)).fetchone()
        return row is not None

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
